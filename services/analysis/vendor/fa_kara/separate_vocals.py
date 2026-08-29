"""Persistent Demucs vocal separation for the FA-Kara worker."""

import os

import torch
from demucs import pretrained
from demucs.apply import apply_model
from demucs.audio import convert_audio

_DEMUCS_MODEL = None
_DEMUCS_MODEL_NAME = None
_SUPPORTED_MODELS = {"htdemucs", "htdemucs_ft"}


def demucs_model_name():
    model_name = os.environ.get("FA_KARA_DEMUCS_MODEL", "htdemucs_ft").strip()
    if model_name not in _SUPPORTED_MODELS:
        supported = ", ".join(sorted(_SUPPORTED_MODELS))
        raise ValueError(f"FA_KARA_DEMUCS_MODEL must be one of: {supported}")
    return model_name


def separate_vocals(audio_channels, sample_rate, *, use_gpu=True):
    """Return a mono vocal stem while retaining the selected model for later jobs."""
    global _DEMUCS_MODEL, _DEMUCS_MODEL_NAME
    device = torch.device("cuda" if use_gpu and torch.cuda.is_available() else "cpu")
    model_name = demucs_model_name()
    if _DEMUCS_MODEL is None or _DEMUCS_MODEL_NAME != model_name:
        _DEMUCS_MODEL = pretrained.get_model(model_name)
        _DEMUCS_MODEL.eval()
        _DEMUCS_MODEL.to(device)
        _DEMUCS_MODEL_NAME = model_name
    model = _DEMUCS_MODEL
    waveform = torch.as_tensor(audio_channels.T, dtype=torch.float32)
    waveform = convert_audio(waveform, sample_rate, model.samplerate, model.audio_channels)
    reference = waveform.mean(0)
    reference_mean = reference.mean()
    reference_std = reference.std().clamp_min(1e-8)
    normalized = (waveform - reference_mean) / reference_std
    with torch.inference_mode():
        sources = apply_model(
            model, normalized.unsqueeze(0), device=device,
            shifts=1, split=True, overlap=0.25, progress=False,
        )[0]
    vocals = sources[model.sources.index("vocals")] * reference_std + reference_mean
    return vocals.mean(0).cpu().numpy(), int(model.samplerate)
