#!/usr/bin/env python3
"""videoassist - CLI video editing assistant (ffmpeg + optional AI edit plans).

Commands:
  silence-cut  remove silent parts automatically (jump cuts)
  vertical     convert to 9:16 for TikTok / Reels / Shorts
  captions     burn an .srt subtitle file into the video
  speed        change playback speed (audio pitch preserved)
  plan         AI edit plan from a transcript (needs ANTHROPIC_API_KEY)
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request


# ---------- helpers ----------

def need_ffmpeg():
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"Error: {tool} not found. Install ffmpeg first (https://ffmpeg.org/download.html).")


def duration_of(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def run(cmd):
    print("$", " ".join(cmd))
    subprocess.run(cmd, check=True)


# ---------- silence cutting (pure logic, unit tested) ----------

def parse_silences(stderr_text, total):
    """Parse ffmpeg silencedetect output into [(start, end), ...]."""
    silences, start = [], None
    for line in stderr_text.splitlines():
        m = re.search(r"silence_start:\s*(-?[\d.]+)", line)
        if m:
            start = max(0.0, float(m.group(1)))
            continue
        m = re.search(r"silence_end:\s*([\d.]+)", line)
        if m and start is not None:
            silences.append((start, float(m.group(1))))
            start = None
    if start is not None:  # silence runs to the end of the file
        silences.append((start, total))
    return silences


def compute_keep(silences, total, pad=0.1, min_keep=0.15):
    """Invert silences into segments to keep, padded and merged."""
    keep, cursor = [], 0.0
    for s, e in sorted(silences):
        if s > cursor:
            keep.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < total:
        keep.append((cursor, total))
    padded = [(max(0.0, a - pad), min(total, b + pad)) for a, b in keep]
    merged = []
    for a, b in padded:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return [(a, b) for a, b in merged if b - a >= min_keep]


def build_filter(segments):
    parts = []
    for i, (a, b) in enumerate(segments):
        parts.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}];")
        parts.append(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[a{i}];")
    labels = "".join(f"[v{i}][a{i}]" for i in range(len(segments)))
    parts.append(f"{labels}concat=n={len(segments)}:v=1:a=1[outv][outa]")
    return "\n".join(parts)


def cmd_silence_cut(a):
    need_ffmpeg()
    total = duration_of(a.input)
    res = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", a.input, "-af",
         f"silencedetect=noise={a.db}dB:d={a.min_silence}", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    silences = parse_silences(res.stderr, total)
    segments = compute_keep(silences, total, a.pad)
    if not segments:
        sys.exit("Nothing to keep. Try a lower --db (e.g. -40).")
    kept = sum(b - x for x, b in segments)
    print(f"Found {len(silences)} silent parts. Keeping {kept:.1f}s of {total:.1f}s.")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(build_filter(segments))
        script = f.name
    try:
        run(["ffmpeg", "-y", "-hide_banner", "-i", a.input,
             "-filter_complex_script", script,
             "-map", "[outv]", "-map", "[outa]", a.output])
    finally:
        os.unlink(script)


# ---------- simple edits ----------

def cmd_vertical(a):
    need_ffmpeg()
    vf = "crop=ih*9/16:ih,scale=1080:1920"
    if a.blur:  # keep full frame on top of a blurred background
        vf = ("split[a][b];[a]scale=1080:1920,boxblur=20:5[bg];"
              "[b]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
        run(["ffmpeg", "-y", "-i", a.input, "-filter_complex", vf, "-c:a", "copy", a.output])
    else:
        run(["ffmpeg", "-y", "-i", a.input, "-vf", vf, "-c:a", "copy", a.output])


def cmd_captions(a):
    need_ffmpeg()
    srt = a.srt.replace("\\", "/").replace(":", "\\:")
    style = "FontSize=18,Outline=2,Alignment=2,MarginV=60"
    run(["ffmpeg", "-y", "-i", a.input, "-vf",
         f"subtitles='{srt}':force_style='{style}'", "-c:a", "copy", a.output])


def atempo_chain(f):
    """atempo only accepts 0.5-2.0 per filter, so chain for larger factors."""
    parts = []
    while f > 2.0:
        parts.append("atempo=2.0")
        f /= 2.0
    while f < 0.5:
        parts.append("atempo=0.5")
        f /= 0.5
    parts.append(f"atempo={f:.4f}")
    return ",".join(parts)


def cmd_speed(a):
    need_ffmpeg()
    run(["ffmpeg", "-y", "-i", a.input,
         "-filter_complex",
         f"[0:v]setpts=PTS/{a.factor}[v];[0:a]{atempo_chain(a.factor)}[a]",
         "-map", "[v]", "-map", "[a]", a.output])


# ---------- AI edit plan (optional) ----------

PROMPT = """You are a short-form video editor. From the transcript below, give:
1. HOOK: 3 stronger opening lines (first 3 seconds).
2. CUTS: parts that drag or repeat and should be trimmed (quote the start of each).
3. PACING: where to add a zoom, b-roll or text overlay.
4. CAPTION: one caption + 5 hashtags.
Be concise and specific.

TRANSCRIPT:
{t}"""


def cmd_plan(a):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        sys.exit("Set ANTHROPIC_API_KEY first (export ANTHROPIC_API_KEY=...).")
    text = open(a.transcript, encoding="utf-8").read()[:20000]
    body = json.dumps({
        "model": os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5"),
        "max_tokens": 1000,
        "messages": [{"role": "user", "content": PROMPT.format(t=text)}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    print("".join(b.get("text", "") for b in data["content"]))


# ---------- CLI ----------

def main():
    p = argparse.ArgumentParser(prog="videoassist", description="AI-assisted video editing CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("silence-cut", help="remove silent parts")
    s.add_argument("input"); s.add_argument("-o", "--output", default="cut.mp4")
    s.add_argument("--db", type=int, default=-30, help="silence threshold in dB")
    s.add_argument("--min-silence", type=float, default=0.5, help="min silence length (s)")
    s.add_argument("--pad", type=float, default=0.1, help="padding around speech (s)")
    s.set_defaults(fn=cmd_silence_cut)

    v = sub.add_parser("vertical", help="convert to 9:16")
    v.add_argument("input"); v.add_argument("-o", "--output", default="vertical.mp4")
    v.add_argument("--blur", action="store_true", help="blurred background instead of crop")
    v.set_defaults(fn=cmd_vertical)

    c = sub.add_parser("captions", help="burn subtitles")
    c.add_argument("input"); c.add_argument("srt")
    c.add_argument("-o", "--output", default="captioned.mp4")
    c.set_defaults(fn=cmd_captions)

    sp = sub.add_parser("speed", help="change speed")
    sp.add_argument("input"); sp.add_argument("-f", "--factor", type=float, default=1.25)
    sp.add_argument("-o", "--output", default="speed.mp4")
    sp.set_defaults(fn=cmd_speed)

    pl = sub.add_parser("plan", help="AI edit plan from a transcript")
    pl.add_argument("transcript")
    pl.set_defaults(fn=cmd_plan)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
