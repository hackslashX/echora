import numpy as np

from echora_analysis.audio import deterministic_windows


def test_short_audio_is_wrapped_to_one_window() -> None:
    source = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    windows = deterministic_windows(source, sample_rate=1, seconds=5)
    assert len(windows) == 1
    np.testing.assert_array_equal(windows[0], [1.0, 2.0, 3.0, 1.0, 2.0])


def test_long_audio_uses_three_fixed_windows() -> None:
    source = np.arange(100, dtype=np.float32)
    windows = deterministic_windows(source, sample_rate=1, seconds=10)
    assert [window[0] for window in windows] == [10, 45, 80]
