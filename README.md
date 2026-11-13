# videoassist 🎞️

CLI video editing assistant for short-form creators. Auto-removes silence, converts
to vertical 9:16, burns captions, changes speed, and (optionally) asks an AI for an
edit plan from your transcript. Pure Python, no pip dependencies. Needs **ffmpeg**.

## Install ffmpeg

- Mac: `brew install ffmpeg`
- Windows: `winget install ffmpeg`
- Linux: `sudo apt install ffmpeg`

## Usage

```bash
# Remove silent gaps (jump-cut style)
python videoassist.py silence-cut raw.mp4 -o cut.mp4 --db -30 --min-silence 0.5

# 16:9 -> 9:16 (center crop, or --blur to keep full frame)
python videoassist.py vertical cut.mp4 -o vertical.mp4
python videoassist.py vertical cut.mp4 -o vertical.mp4 --blur

# Burn subtitles from an .srt
python videoassist.py captions vertical.mp4 subs.srt -o final.mp4

# Speed up 1.25x (audio pitch preserved)
python videoassist.py speed final.mp4 -f 1.25 -o fast.mp4

# AI edit plan from a transcript (hooks, cuts, pacing, caption)
export ANTHROPIC_API_KEY=your_key
python videoassist.py plan transcript.txt
```

Typical workflow: `silence-cut` → `vertical` → `captions` → upload.

## Tuning silence-cut

| Flag | Default | Meaning |
|------|---------|---------|
| `--db` | -30 | Quieter than this = silence. Noisy room? Try -25. Quiet? Try -40. |
| `--min-silence` | 0.5 | Only cut gaps longer than this (seconds). |
| `--pad` | 0.1 | Keep this much around speech so words don't get clipped. |

## Notes

- The `plan` command is optional and needs an Anthropic API key. Set `CLAUDE_MODEL` to override the default model.
- `captions` needs an ffmpeg build with libass (most builds have it).

## Tests

```bash
pip install pytest && pytest
```

## License

MIT
