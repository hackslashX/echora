"""Whole-track seek-bar peaks, generated only by the sync pipeline."""
from __future__ import annotations

import numpy as np

from .audio import decode_audio_channels

WAVEFORM_REVISION = "1"
SAMPLE_RATE = 24_000
PEAK_COUNT = 1024


def waveform_peaks(samples: np.ndarray, count: int = PEAK_COUNT) -> list[float]:
    """Equal-time peak buckets across all channels, including the final sample."""
    if count < 1 or samples.size == 0 or not np.isfinite(samples).all():
        raise ValueError("Waveform requires finite, nonempty samples and a positive bucket count")
    amplitude = np.abs(samples)
    if amplitude.ndim > 1:
        amplitude = amplitude.max(axis=1)
    # Short clips use fewer buckets rather than repeating or inventing samples.
    buckets = np.array_split(amplitude, min(count, len(amplitude)))
    peaks = np.array([block.max() for block in buckets])
    maximum = float(peaks.max())
    if maximum > 0:
        peaks /= maximum
    return [round(float(value), 4) for value in peaks]


def store_waveform(connection, track_id, audio: bytes) -> None:
    from psycopg.types.json import Jsonb

    samples = decode_audio_channels(audio, sample_rate=SAMPLE_RATE)
    peaks = waveform_peaks(samples)
    with connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO track_waveforms (track_id, revision, duration_seconds, peaks)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (track_id) DO UPDATE SET revision=EXCLUDED.revision,
                 duration_seconds=EXCLUDED.duration_seconds, peaks=EXCLUDED.peaks, created_at=now()""",
            (track_id, WAVEFORM_REVISION, len(samples) / SAMPLE_RATE, Jsonb(peaks)),
        )
