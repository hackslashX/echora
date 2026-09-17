"""Local-only, per-call Mel-Band-Roformer vocal separation at 44.1 kHz stereo.

No resampling, normalization, clipping or network fallback. See vendor/roformer/NOTICE
for source attribution, model licensing and author permission references. Full-track buffers stay
on CPU; only one inference chunk and the model reside on the accelerator.
"""

from collections.abc import Callable
from contextlib import nullcontext
import gc

import numpy as np
import torch

MODEL_ID = "KimberleyJSN/melbandroformer"
MODEL_REVISION = "ac9b0614ab3cd7f77219e18ba494dfd93956c348"
MODEL_FILENAME = "MelBandRoformer.ckpt"
SAMPLE_RATE = 44100
_SOURCE_REVISION = "25f44ffb55ee3c301281bba21b2d6d311cb69ae2"
_CHUNK_SIZE = 352800
_OVERLAP = 2
SEPARATION_REVISION = (
    f"{MODEL_ID}@{MODEL_REVISION}/{MODEL_FILENAME}:overlap{_OVERLAP}:chunk{_CHUNK_SIZE}:"
    f"config_vocals_mel_band_roformer.yaml@{_SOURCE_REVISION}:"
    f"source@{_SOURCE_REVISION}:echora-v1"
)
# Exact upstream model config; no YAML loader or training config dependency.
_MODEL_CONFIG = dict(
    dim=384, depth=6, stereo=True, num_stems=1,
    time_transformer_depth=1, freq_transformer_depth=1, num_bands=60,
    dim_head=64, heads=8, attn_dropout=0, ff_dropout=0, flash_attn=True,
    dim_freqs_in=1025, sample_rate=SAMPLE_RATE, stft_n_fft=2048,
    stft_hop_length=441, stft_win_length=2048, stft_normalized=False,
    mask_estimator_depth=2, multi_stft_resolution_loss_weight=1.0,
    multi_stft_resolutions_window_sizes=(4096, 2048, 1024, 512, 256),
    multi_stft_hop_size=147, multi_stft_normalized=False,
)


def _new_model():
    from .vendor.roformer.mel_band_roformer import MelBandRoformer

    return MelBandRoformer(**_MODEL_CONFIG)


def _load_weights(model):
    from huggingface_hub import hf_hub_download

    path = hf_hub_download(
        repo_id=MODEL_ID, revision=MODEL_REVISION, filename=MODEL_FILENAME,
        local_files_only=True,
    )
    state = torch.load(path, map_location="cpu", weights_only=True)
    try:
        model.load_state_dict(state, strict=True)
    finally:
        del state


def _predict(model, part: np.ndarray, device: torch.device) -> np.ndarray:
    """Drop device tensor references even when a retained traceback escapes."""
    batch = prediction = None
    try:
        batch = torch.from_numpy(np.ascontiguousarray(part)).unsqueeze(0).to(device)
        amp = torch.autocast("cuda", dtype=torch.float16) if device.type == "cuda" else nullcontext()
        with torch.inference_mode(), amp:
            prediction = model(batch)
        if not isinstance(prediction, torch.Tensor) or prediction.shape != batch.shape:
            raise ValueError("Roformer returned an invalid chunk shape")
        result = prediction.detach().to(device="cpu", dtype=torch.float32).numpy().copy()[0]
        if not np.isfinite(result).all():
            raise ValueError("Roformer returned non-finite audio")
        return result
    finally:
        batch = prediction = None


def _demix(model, waveform: np.ndarray, device: torch.device, check: Callable[[], None]):
    chunk = _CHUNK_SIZE
    step = chunk // _OVERLAP
    fade = chunk // 10
    border = chunk - step
    original_length = len(waveform)
    # Pad short clips before the upstream reflect/crop decision. Track the decision
    # explicitly: upstream erroneously decides cropping from the padded length.
    mix = np.pad(waveform.T, ((0, 0), (0, max(0, chunk - original_length))))
    reflected = mix.shape[1] > 2 * border
    if reflected:
        mix = np.pad(mix, ((0, 0), (border, border)), mode="reflect")
    total = mix.shape[1]
    # float64 accumulation avoids overflow for finite float32 model outputs.
    result = np.zeros((2, total), dtype=np.float64)
    counter = np.zeros(total, dtype=np.float64)
    window = np.ones(chunk, dtype=np.float32)
    window[:fade] = np.linspace(0, 1, fade, dtype=np.float32)
    window[-fade:] = np.linspace(1, 0, fade, dtype=np.float32)
    for start in range(0, total, step):
        check()
        part = mix[:, start:start + chunk]
        length = part.shape[1]
        if length < chunk:
            mode = "reflect" if length > chunk // 2 + 1 else "constant"
            part = np.pad(part, ((0, 0), (0, chunk - length)), mode=mode)
        prediction = _predict(model, part, device)
        weights = window.copy()
        if start == 0:
            weights[:fade] = 1
        if start + chunk >= total:
            weights[-fade:] = 1
        result[:, start:start + length] += prediction[:, :length].astype(np.float64) * weights[:length]
        counter[start:start + length] += weights[:length]
    check()
    if not np.all(counter > 0):
        raise ValueError("Roformer overlap left uncovered samples")
    result /= counter
    offset = border if reflected else 0
    return np.ascontiguousarray(result[:, offset:offset + original_length].T, dtype=np.float32)


def separate_vocals(
    waveform: np.ndarray, check: Callable[[], None] = lambda: None,
) -> np.ndarray:
    """Separate finite float32 (frames, 2) audio; cancellation exceptions propagate.

    Empty audio returns a fresh empty array without loading weights. Nonempty calls
    each load a fresh model from the pinned local HF cache and release it in finally.
    The caller must already have cached the checkpoint; missing cache is an error.
    """
    if not isinstance(waveform, np.ndarray) or waveform.dtype != np.float32:
        raise ValueError("waveform must be a float32 numpy array")
    if waveform.ndim != 2 or waveform.shape[1] != 2:
        raise ValueError("waveform must have shape (frames, 2)")
    if not np.isfinite(waveform).all():
        raise ValueError("waveform must contain only finite samples")
    check()
    if not len(waveform):
        return waveform.copy()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = None
    try:
        model = _new_model()
        _load_weights(model)
        check()
        model.eval()
        model.to(device)
        result = _demix(model, waveform, device, check)
        if result.shape != waveform.shape or result.dtype != np.float32:
            raise ValueError("Roformer returned an invalid waveform shape or dtype")
        if not np.isfinite(result).all():
            raise ValueError("Roformer returned non-finite audio")
        return result
    finally:
        try:
            # Move parameters to CPU even if an exception traceback retains the model.
            if model is not None:
                model.cpu()
        finally:
            model = None
            gc.collect()
            if device.type == "cuda":
                torch.cuda.empty_cache()
