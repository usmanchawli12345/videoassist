from videoassist import parse_silences, compute_keep, build_filter, atempo_chain

LOG = """
[silencedetect @ 0x1] silence_start: 2.0
[silencedetect @ 0x1] silence_end: 4.0 | silence_duration: 2.0
[silencedetect @ 0x1] silence_start: 8.5
"""


def test_parse_silences_incl_trailing():
    assert parse_silences(LOG, 10.0) == [(2.0, 4.0), (8.5, 10.0)]


def test_compute_keep():
    keep = compute_keep([(2.0, 4.0), (8.5, 10.0)], 10.0, pad=0.0)
    assert keep == [(0.0, 2.0), (4.0, 8.5)]


def test_padding_merges_close_segments():
    keep = compute_keep([(2.0, 2.1)], 5.0, pad=0.2)
    assert keep == [(0.0, 5.0)]


def test_no_silence_keeps_everything():
    assert compute_keep([], 7.0) == [(0.0, 7.0)]


def test_build_filter_has_concat():
    f = build_filter([(0, 1), (2, 3)])
    assert "concat=n=2" in f and "[v1][a1]" in f


def test_atempo_chain():
    assert atempo_chain(1.25) == "atempo=1.2500"
    assert atempo_chain(4.0).count("atempo") == 2
