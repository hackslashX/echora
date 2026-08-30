from __future__ import annotations

import subprocess

import numpy as np


def decode_audio(data: bytes, sample_rate: int = 24_000) -> np.ndarray:
    process = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
            "-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "f32le", "pipe:1",
        ],
        input=data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        message = process.stderr.decode(errors="replace").strip()
        raise ValueError(f"ffmpeg could not decode audio: {message[-500:]}")
    waveform = np.frombuffer(process.stdout, dtype="<f4").copy()
    if waveform.size == 0:
        raise ValueError("Decoded audio is empty")
    return waveform


def decode_audio_channels(data: bytes, sample_rate: int = 44_100, channels: int = 2) -> np.ndarray:
    process = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
            "-vn", "-ac", str(channels), "-ar", str(sample_rate), "-f", "f32le", "pipe:1",
        ],
        input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if process.returncode != 0:
        message = process.stderr.decode(errors="replace").strip()
        raise ValueError(f"ffmpeg could not decode audio: {message[-500:]}")
    waveform = np.frombuffer(process.stdout, dtype="<f4").copy()
    if waveform.size == 0 or waveform.size % channels:
        raise ValueError("Decoded audio is empty or has incomplete channels")
    return waveform.reshape(-1, channels)


def full_coverage_windows(
    waveform: np.ndarray,
    sample_rate: int = 24_000,
    seconds: int = 10,
    stride_seconds: int = 5,
) -> list[np.ndarray]:
    """Cover the complete waveform with overlapping fixed-duration windows."""
    size = sample_rate * seconds
    stride = sample_rate * stride_seconds
    if stride <= 0 or stride > size:
        raise ValueError("Window stride must be greater than zero and no longer than the window")
    if waveform.size < size:
        repeats = int(np.ceil(size / waveform.size))
        return [np.tile(waveform, repeats)[:size].astype(np.float32)]

    starts = list(range(0, waveform.size - size + 1, stride))
    final_start = waveform.size - size
    if starts[-1] != final_start:
        starts.append(final_start)
    return [np.ascontiguousarray(waveform[start:start + size], dtype=np.float32) for start in starts]


def deterministic_windows(
    waveform: np.ndarray,
    sample_rate: int = 24_000,
    seconds: int = 10,
    positions: tuple[float, ...] = (0.15, 0.50, 0.85),
) -> list[np.ndarray]:
    size = sample_rate * seconds
    if waveform.size < size:
        repeats = int(np.ceil(size / waveform.size))
        return [np.tile(waveform, repeats)[:size].astype(np.float32)]

    windows = []
    for position in positions:
        center = round(position * waveform.size)
        start = min(max(0, center - size // 2), waveform.size - size)
        windows.append(np.ascontiguousarray(waveform[start : start + size], dtype=np.float32))
    return windows
