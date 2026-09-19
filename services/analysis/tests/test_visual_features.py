import numpy as np

from echora_analysis.visual_features import HOP_SECONDS, SAMPLE_RATE, extract_visual_features


def test_visual_features_are_compact_aligned_and_finite():
    seconds = 1.2
    time = np.arange(round(seconds * SAMPLE_RATE), dtype=np.float32) / SAMPLE_RATE
    result = extract_visual_features(.25 * np.sin(2 * np.pi * 440 * time))

    frames = len(result["bands"])
    assert frames > 8
    assert result["hop_seconds"] == HOP_SECONDS
    assert len(result["level"]) == len(result["onset"]) == len(result["chroma"]) == frames
    assert all(len(frame) == 24 and all(0 <= value <= 1 for value in frame) for frame in result["bands"])
    assert all(len(frame) == 12 for frame in result["chroma"])


def test_visual_features_reject_invalid_audio():
    try:
        extract_visual_features(np.zeros(0, dtype=np.float32))
    except ValueError:
        pass
    else:
        raise AssertionError("empty input must be rejected")
