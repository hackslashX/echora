from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
import os
import platform
import threading
import uuid
import logging

import essentia.standard as es
import numpy as np
import onnxruntime as ort
import psycopg
import torch
from psycopg.types.json import Jsonb

from .audio import decode_audio
from .navidrome import NavidromeClient

logger = logging.getLogger(__name__)

VOICE_EMBEDDING_TYPE = "voice-gender"
VOICE_MODEL_NAME = "mtg-jamendo-voice-gender-v2"

# Essentia MTG-Jamendo classification heads (ONNX): gender (female/male) and
# voice_instrumental, both consuming discogs-effnet frame embeddings computed
# from log-mel patches. All three files are preloaded by
# echora_analysis.download_models into ESSENTIA_MODELS_DIR; nothing is
# downloaded at inference time.
_EMBEDDING_MODEL_FILE = "discogs-effnet-bsdynamic-1.onnx"
_GENDER_MODEL_FILE = "gender-discogs-effnet-1.onnx"
_VOICE_INSTRUMENTAL_MODEL_FILE = "voice_instrumental-discogs-effnet-1.onnx"
_PATCH_FRAMES = 128

_model: tuple | None = None
_model_lock = threading.Lock()


def _model_directory() -> str:
    directory = os.environ.get("ESSENTIA_MODELS_DIR", "/data/models/essentia")
    return directory


def _require_model_file(filename: str) -> str:
    path = os.path.join(_model_directory(), filename)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Essentia model {filename} is missing from {os.environ.get('ESSENTIA_MODELS_DIR', '/data/models/essentia')}; "
            "run `python -m echora_analysis.download_models` on a machine with network access"
        )
    return path


def _aggregate_outputs(gender: np.ndarray, voice: np.ndarray) -> dict[str, float]:
    """Combine [female, male] and [instrumental, voice] patch probabilities."""
    gender = np.asarray(gender, dtype=np.float32)
    voice = np.asarray(voice, dtype=np.float32)
    if gender.shape != voice.shape or gender.ndim != 2 or gender.shape[1] != 2:
        raise ValueError(f"Unexpected classifier output shapes: gender={gender.shape}, voice={voice.shape}")
    instrumental = np.clip(voice[:, 0], 0.0, 1.0)
    vocal = np.clip(voice[:, 1], 0.0, 1.0)
    values = {
        "instrumental": float(instrumental.mean()),
        "female": float((vocal * np.clip(gender[:, 0], 0.0, 1.0)).mean()),
        "male": float((vocal * np.clip(gender[:, 1], 0.0, 1.0)).mean()),
    }
    total = sum(values.values()) or 1.0
    return {label: value / total for label, value in values.items()}


class VoiceGenderModel:
    """Voice-activity and vocal-gender classifier over 16 kHz mono audio.

    Returns the mean activation per class across the whole track. These are
    calibrated per track by the caller (library percentile), which is what tag
    matching consumes.
    """

    name = VOICE_MODEL_NAME
    labels = ("instrumental", "female", "male")

    def __init__(self) -> None:
        embedding_graph = _require_model_file(_EMBEDDING_MODEL_FILE)
        gender_graph = _require_model_file(_GENDER_MODEL_FILE)
        voice_graph = _require_model_file(_VOICE_INSTRUMENTAL_MODEL_FILE)
        options = ort.SessionOptions()
        threads = max(4, (os.cpu_count() or 4) // 2)
        options.intra_op_num_threads = options.inter_op_num_threads = threads
        self._embedder = ort.InferenceSession(embedding_graph, options)
        self._gender = ort.InferenceSession(gender_graph, options)
        self._voice = ort.InferenceSession(voice_graph, options)
        # MusiCNN input parameters, hardcoded upstream to match training. Use
        # essentia's own TensorflowInputMusiCNN so the features match the
        # classifier's preprocessing exactly ((mel+1)*10000 -> log10, 96 bands).
        self._input = es.TensorflowInputMusiCNN()

    def _mel_patches(self, waveform: np.ndarray) -> np.ndarray:
        hop = 256
        limit = waveform.size - 512 + 1
        frames = []
        for start in range(0, max(limit, 0), hop):
            frames.append(self._input(waveform[start:start + 512]))
        if len(frames) < _PATCH_FRAMES:
            raise ValueError("Audio is too short for voice classification")
        usable = (len(frames) // _PATCH_FRAMES) * _PATCH_FRAMES
        stacked = np.stack(frames[:usable]).astype(np.float32)
        return stacked.reshape(-1, _PATCH_FRAMES, stacked.shape[-1])

    def classify(self, waveform: np.ndarray) -> dict[str, float]:
        if waveform.size == 0:
            raise ValueError("Decoded audio is empty")
        patches = self._mel_patches(waveform)
        embeddings = self._embedder.run(["embeddings"], {self._embedder.get_inputs()[0].name: patches})[0]
        gender = np.asarray(
            self._gender.run(None, {self._gender.get_inputs()[0].name: embeddings})[0],
            dtype=np.float32,
        )
        voice = np.asarray(
            self._voice.run(None, {self._voice.get_inputs()[0].name: embeddings})[0],
            dtype=np.float32,
        )
        # Preserve vocal presence in gender evidence. Renormalizing female and
        # male independently lets tiny, arbitrary activations from an
        # instrumental patch look decisive.
        return _aggregate_outputs(gender, voice)


def shared_voice_model() -> VoiceGenderModel:
    global _model
    with _model_lock:
        if _model is None:
            _model = (VoiceGenderModel(),)
        return _model[0]


def _vector_literal(vector) -> str:
    return "[" + ",".join(f"{float(value):.9g}" for value in vector) + "]"


def _create_run(connection: psycopg.Connection) -> uuid.UUID:
    config = {
        "model": VOICE_MODEL_NAME,
        "embedding": "discogs-effnet-bsdynamic-1",
        "labels": list(VoiceGenderModel.labels),
        "aggregation": "mean_joint_activation",
        "preprocessing": "essentia-tensorflow-input-musicnn",
        "model_sha256": {
            _EMBEDDING_MODEL_FILE: "a280825b334797cf677939db8cd5762c0392aedd0ca6415dbc1cd083f045e43c",
            _GENDER_MODEL_FILE: "e3e865d4bf36d4817f32ddab9452b2729f9e33a4d068d1c44ea44972a7999e91",
            _VOICE_INSTRUMENTAL_MODEL_FILE: "20155e4c439714b0c45c08644b73c8e12d9dccb173bd4ab9934bf1e5aee837ca",
        },
    }
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    environment = {"python": platform.python_version(), "torch": torch.__version__, "device": "cpu"}
    with connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO analysis_runs
                 (kind, model_name, model_revision, config_hash, config, environment, device, precision, status, started_at)
               VALUES ('voice_classification', %s, 'joint-v2', %s, %s, %s, 'cpu', 'float32', 'running', now())
               ON CONFLICT (kind, model_name, model_revision, config_hash)
               DO UPDATE SET status='running', started_at=now(), finished_at=NULL RETURNING id""",
            (VOICE_MODEL_NAME, config_hash, Jsonb(config), Jsonb(environment)),
        )
        return cursor.fetchone()[0]


def _store_activation(connection: psycopg.Connection, track_id: uuid.UUID, run_id: uuid.UUID, values: dict[str, float]) -> None:
    vector = [values[label] for label in VoiceGenderModel.labels]
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM embeddings WHERE track_id=%s AND run_id=%s AND embedding_type=%s", (track_id, run_id, VOICE_EMBEDDING_TYPE))
        cursor.execute(
            """INSERT INTO embeddings
                 (track_id, run_id, embedding_type, dimension, aggregation, embedding)
               VALUES (%s, %s, %s, %s, 'mean_activation', %s::vector)""",
            (track_id, run_id, VOICE_EMBEDDING_TYPE, len(vector), _vector_literal(vector)),
        )


def _fetch_stream(client: NavidromeClient, source_id: str) -> np.ndarray:
    return decode_audio(client.audio_bytes(source_id), sample_rate=16_000)


def backfill_voice(
    url: str, username: str, password: str,
    progress: Callable[[dict[str, object]], None] | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    """Classify lead-vocal gender for every track that lacks voice evidence.

    Stores one 3-dimensional vector per track in the embeddings table
    (embedding_type='voice-gender'): [instrumental, female, male] mean
    activations, normalized to sum to one.
    """
    report = progress or (lambda _: None)
    summary = {"total": 0, "classified": 0, "failed": 0}
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection, NavidromeClient(url, username, password) as client:
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT DISTINCT ON (ts.track_id) ts.track_id, ts.external_id, t.title
                   FROM track_sources ts JOIN tracks t ON t.id=ts.track_id
                   WHERE ts.source_type='subsonic'
                     AND NOT EXISTS (
                       SELECT 1 FROM embeddings e JOIN analysis_runs ar ON ar.id=e.run_id
                       WHERE e.track_id=ts.track_id AND e.embedding_type=%s AND ar.model_name=%s
                     )
                   ORDER BY ts.track_id, ts.id
                   LIMIT %s""",
                (VOICE_EMBEDDING_TYPE, VOICE_MODEL_NAME, limit),
            )
            tracks = cursor.fetchall()
        if not tracks:
            report({"phase": "planning", "message": "Voice classification already current",
                    "completed": 0, "total": 0, "unit": "tracks"})
            return summary
        summary["total"] = len(tracks)
        report({"phase": "models", "message": "Loading voice classifier", "completed": 0, "total": 1, "unit": "models"})
        model = shared_voice_model()
        run_id = _create_run(connection)
        connection.commit()
        for index, (track_id, external_id, title) in enumerate(tracks):
            try:
                waveform = _fetch_stream(client, str(external_id))
                values = model.classify(waveform)
                _store_activation(connection, track_id, run_id, values)
                summary["classified"] += 1
                connection.commit()
            except Exception:
                connection.rollback()
                summary["failed"] += 1
                logger.exception("Voice classification failed for track %s", track_id)
            report({"phase": "voice", "message": f"Classifying vocals for {title}",
                    "completed": index + 1, "total": len(tracks), "unit": "tracks",
                    "summary": summary})
        with connection.cursor() as cursor:
            cursor.execute("UPDATE analysis_runs SET status='complete', finished_at=now() WHERE id=%s", (run_id,))
        connection.commit()
    return summary
