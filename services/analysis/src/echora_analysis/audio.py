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
