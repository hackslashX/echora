import unittest

import numpy as np

from echora_analysis.waveforms import waveform_peaks


class WaveformTests(unittest.TestCase):
    def test_peaks_cover_whole_track_and_last_sample(self):
        samples = np.zeros((2051, 2), dtype=np.float32)
        samples[0, 0] = .5
        samples[-1, 1] = 1
        peaks = waveform_peaks(samples)
        self.assertEqual(len(peaks), 1024)
        self.assertEqual(peaks[0], .5)
        self.assertEqual(peaks[-1], 1)
        self.assertTrue(all(value == 0 for value in peaks[1:-1]))

    def test_antiphase_stereo_does_not_cancel(self):
        samples = np.array([[.25, -.25], [.5, -.5]], dtype=np.float32)
        self.assertEqual(waveform_peaks(samples, 2), [.5, 1])

    def test_silence_and_short_clips(self):
        self.assertEqual(waveform_peaks(np.zeros((3, 2))), [0, 0, 0])
        self.assertEqual(waveform_peaks(np.array([.2])), [1])

    def test_reject_invalid_audio(self):
        for samples in (np.array([]), np.array([np.nan]), np.array([np.inf])):
            with self.subTest(samples=samples), self.assertRaises(ValueError):
                waveform_peaks(samples)

    def test_invalid_bucket_count(self):
        with self.assertRaises(ValueError):
            waveform_peaks(np.ones(4), 0)
