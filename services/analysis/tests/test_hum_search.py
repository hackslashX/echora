import numpy as np

from echora_analysis.hum_search import overlapping_windows


def test_short_recording_is_zero_padded_to_one_window():
    waveform = np.ones(24_000 * 3, dtype=np.float32)

    windows = overlapping_windows(waveform)

    assert len(windows) == 1
    start, end, audio = windows[0]
    assert start == 0
    assert end == 3
    assert audio.shape == (24_000 * 10,)
    assert np.all(audio[: 24_000 * 3] == 1)
    assert np.all(audio[24_000 * 3 :] == 0)


def test_long_recording_uses_overlapping_windows_and_keeps_the_tail():
    waveform = np.arange(24_000 * 22, dtype=np.float32)

    windows = overlapping_windows(waveform)

    assert [round(item[0]) for item in windows] == [0, 5, 10, 12]
    assert all(item[2].shape == (24_000 * 10,) for item in windows)
    assert windows[-1][1] == 22
