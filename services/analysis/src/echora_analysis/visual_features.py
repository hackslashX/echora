"""Compact, precomputed audio features for every browser visualizer.

The browser receives one shared timeline instead of each visualizer running its
own FFT, beat detector, and band aggregation against the media element.
"""
from __future__ import annotations

import math

import librosa
import numpy as np
from psycopg.types.json import Jsonb

from .audio import decode_audio

VISUAL_FEATURE_REVISION = "1"
SAMPLE_RATE = 22_050
HOP_SECONDS = 0.1
HOP_LENGTH = round(SAMPLE_RATE * HOP_SECONDS)
FRAME_LENGTH = 2_048
BAND_COUNT = 24


def _round(values: np.ndarray, digits: int = 4) -> list[list[float]]:
    return [[round(float(value), digits) for value in row] for row in values]


def extract_visual_features(samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> dict[str, object]:
    """Return log-frequency STFT bands plus musical and onset features at 10 Hz."""
    if sample_rate != SAMPLE_RATE:
        raise ValueError("Visual features require 22050 Hz audio")
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim != 1 or not samples.size or not np.isfinite(samples).all():
        raise ValueError("Visual features require finite, nonempty mono audio")

    stft = librosa.stft(samples, n_fft=FRAME_LENGTH, hop_length=HOP_LENGTH, window="hann", center=True)
    magnitude = np.abs(stft)
    power = magnitude * magnitude
    mel = librosa.feature.melspectrogram(S=power, sr=sample_rate, n_mels=BAND_COUNT, fmin=30, fmax=10_000)
    bands = np.log1p(mel).T
    maximum = float(np.percentile(bands, 99.5))
    bands = np.clip(bands / maximum, 0, 1) if maximum > 0 else np.zeros_like(bands)
    rms = librosa.feature.rms(S=magnitude).reshape(-1)
    centroid = librosa.feature.spectral_centroid(S=magnitude, sr=sample_rate).reshape(-1) / 10_000
    flux = np.maximum(0, np.diff(np.log1p(magnitude), axis=1)).mean(axis=0)
    flux = np.pad(flux, (1, 0))
    flux_max = float(np.percentile(flux, 99.5))
    flux = np.clip(flux / flux_max, 0, 1) if flux_max > 0 else np.zeros_like(flux)
    chroma = librosa.feature.chroma_cqt(y=samples, sr=sample_rate, hop_length=HOP_LENGTH).T
    frame_count = min(len(bands), len(rms), len(centroid), len(flux), len(chroma))
    rms = rms[:frame_count]
    rms_max = float(np.percentile(rms, 99.5))
    rms = np.clip(rms[:frame_count] / rms_max, 0, 1) if rms_max > 0 else np.zeros(frame_count)
    onset = librosa.onset.onset_strength(S=power, sr=sample_rate, hop_length=HOP_LENGTH)[:frame_count]
    onset_max = float(np.percentile(onset, 99.5))
    onset = np.clip(onset / onset_max, 0, 1) if onset_max > 0 else np.zeros(frame_count)
    return {
        "revision": VISUAL_FEATURE_REVISION,
        "sample_rate": sample_rate,
        "hop_seconds": HOP_SECONDS,
        "duration_seconds": round(len(samples) / sample_rate, 4),
        "bands": _round(bands[:frame_count]),
        "level": [round(float(value), 4) for value in rms],
        "centroid": [round(float(value), 4) for value in centroid[:frame_count]],
        "flux": [round(float(value), 4) for value in flux[:frame_count]],
        "onset": [round(float(value), 4) for value in onset],
        "chroma": _round(chroma[:frame_count]),
    }


def store_visual_features(connection, track_id, audio: bytes) -> dict[str, object]:
    features = extract_visual_features(decode_audio(audio, SAMPLE_RATE))
    with connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO track_visual_features (track_id, revision, duration_seconds, hop_seconds, features)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (track_id) DO UPDATE SET revision=EXCLUDED.revision,
                 duration_seconds=EXCLUDED.duration_seconds, hop_seconds=EXCLUDED.hop_seconds,
                 features=EXCLUDED.features, created_at=now()""",
            (track_id, VISUAL_FEATURE_REVISION, features["duration_seconds"], HOP_SECONDS, Jsonb(features)),
        )
    return features
