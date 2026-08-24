from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
import os
import platform
import uuid
from collections.abc import Callable

import numpy as np
import psycopg
from psycopg.types.json import Jsonb
import torch

from .audio import decode_audio, deterministic_windows
from .models import AudioEmbeddingModel, MertModel, MuQMuLanModel
from .navidrome import NavidromeClient, NavidromeTrack
from .recordings import store_and_match_fingerprint

CONTENT_NAMESPACE = uuid.UUID("0c300f5d-99d1-48b8-b12a-a52b9556be86")
logger = logging.getLogger(__name__)


@dataclass
class IngestSummary:
    requested: int = 0
    discovered: int = 0
    downloaded: int = 0
    inserted: int = 0
    already_linked: int = 0
    reused_embeddings: int = 0
    embedded_muq: int = 0
    embedded_mert: int = 0
    fingerprinted: int = 0
    recording_matches: int = 0
    failed: int = 0


def _vector_literal(vector: np.ndarray) -> str:
    return "[" + ",".join(f"{float(value):.9g}" for value in vector) + "]"


def _config_hash(value: dict[str, object]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _create_run(connection: psycopg.Connection, model: AudioEmbeddingModel) -> uuid.UUID:
    config = {
        "model": model.name,
        "revision": model.revision,
        "sample_rate": model.sample_rate,
        "windows": [0.15, 0.5, 0.85],
        "window_seconds": model.window_seconds,
        "aggregation": "normalized_mean",
    }
    environment = {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    }
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO analysis_runs
              (kind, model_name, model_revision, config_hash, config, environment,
               device, precision, status, started_at)
            VALUES ('audio_embedding', %s, %s, %s, %s, %s, %s, 'float32', 'running', now())
            ON CONFLICT (kind, model_name, model_revision, config_hash)
            DO UPDATE SET status = 'running', started_at = now(), finished_at = NULL
            RETURNING id
            """,
            (model.name, model.revision, _config_hash(config), Jsonb(config), Jsonb(environment), str(model.device)),
        )
        return cursor.fetchone()[0]


def _has_fingerprint(connection: psycopg.Connection, track_id: uuid.UUID) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM track_fingerprints WHERE track_id=%s", (track_id,))
        return cursor.fetchone() is not None


def _model_has_embedding(connection: psycopg.Connection, track_id: uuid.UUID, run_id: uuid.UUID) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM embeddings WHERE track_id=%s AND run_id=%s AND embedding_type='audio-track'",
            (track_id, run_id),
        )
        return cursor.fetchone() is not None


def _store_embedding(connection: psycopg.Connection, track_id: uuid.UUID, run_id: uuid.UUID, model: AudioEmbeddingModel, windows: list[np.ndarray]) -> None:
    result = model.embed_windows(windows)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO embeddings
              (track_id, run_id, embedding_type, dimension, aggregation, embedding,
               inference_ms, peak_vram_bytes)
            VALUES (%s, %s, 'audio-track', %s, 'normalized_mean', %s::vector, %s, %s)
            ON CONFLICT (track_id, run_id, embedding_type, window_index) DO NOTHING
            """,
            (track_id, run_id, len(result.vector), _vector_literal(result.vector), result.inference_ms, result.peak_vram_bytes),
        )


def _source_track_id(connection: psycopg.Connection, library_id: uuid.UUID, external_id: str) -> uuid.UUID | None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT track_id FROM track_sources WHERE library_id=%s AND source_type='subsonic' AND external_id=%s",
            (library_id, external_id),
        )
        row = cursor.fetchone()
        return row[0] if row else None


def _upsert_track(connection: psycopg.Connection, library_id: uuid.UUID, song: NavidromeTrack, audio_hash: str) -> tuple[uuid.UUID, bool]:
    track_id = uuid.uuid5(CONTENT_NAMESPACE, audio_hash)
    metadata = {"navidrome": song.raw, "identity": "sha256-source-bytes"}
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tracks (id, audio_hash, title, artist, album, year, duration_seconds, genres, metadata)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (audio_hash) DO NOTHING
            RETURNING id
            """,
            (track_id, audio_hash, song.title, song.artist, song.album, song.year, song.duration, [song.genre] if song.genre else [], Jsonb(metadata)),
        )
        inserted = cursor.fetchone() is not None
        cursor.execute("SELECT id FROM tracks WHERE audio_hash=%s", (audio_hash,))
        canonical_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO library_tracks (library_id, track_id, relative_path) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
            (library_id, canonical_id, song.path),
        )
        cursor.execute(
            """
            INSERT INTO track_sources (library_id, track_id, source_type, external_id, source_data)
            VALUES (%s,%s,'subsonic',%s,%s)
            ON CONFLICT (library_id, source_type, external_id)
            DO UPDATE SET track_id=EXCLUDED.track_id, source_data=EXCLUDED.source_data
            """,
            (library_id, canonical_id, song.id, Jsonb(song.raw)),
        )
    return canonical_id, inserted


def _library(connection: psycopg.Connection, url: str) -> uuid.UUID:
    namespace = uuid.uuid5(uuid.NAMESPACE_URL, url.rstrip("/"))
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO libraries (name, root_path, namespace)
            VALUES ('Navidrome', %s, %s)
            ON CONFLICT (namespace) DO UPDATE SET root_path=EXCLUDED.root_path
            RETURNING id
            """,
            (url.rstrip("/"), namespace),
        )
        return cursor.fetchone()[0]


def ingest_navidrome(
    url: str,
    username: str,
    password: str,
    song_ids: list[str],
    progress: Callable[[dict[str, object]], None] | None = None,
    model_total: int = 2,
) -> IngestSummary:
    report = progress or (lambda _: None)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    report({"phase": "models", "message": "Loading semantic model", "completed": 0, "total": model_total, "unit": "models"})
    muq = MuQMuLanModel(os.getenv("MUQ_MODEL_ID", "OpenMuQ/MuQ-MuLan-large"), os.getenv("MUQ_REVISION", "main"), device)
    report({"phase": "models", "message": "Loading acoustic model", "completed": 1, "total": model_total, "unit": "models"})
    mert = MertModel(os.getenv("MERT_MODEL_ID", "m-a-p/MERT-v1-95M"), os.getenv("MERT_REVISION", "main"), device)
    summary = IngestSummary(requested=len(song_ids))

    with psycopg.connect(os.environ["DATABASE_URL"]) as connection, NavidromeClient(
        url, username, password
    ) as navidrome:
        library_id = _library(connection, url)
        muq_run, mert_run = _create_run(connection, muq), _create_run(connection, mert)
        songs = navidrome.tracks(song_ids)
        summary.discovered = len(songs)
        report({"phase": "processing", "message": "Models ready", "completed": 0, "total": len(songs), "unit": "tracks"})
        connection.commit()

        for index, song in enumerate(songs):
            report({
                "phase": "processing", "message": f"Processing {song.title}",
                "track": {"id": song.id, "title": song.title, "artist": song.artist},
                "completed": index, "total": len(songs), "unit": "tracks", "summary": summary.__dict__,
            })
            try:
                known_id = _source_track_id(connection, library_id, song.id)
                if known_id and _has_fingerprint(connection, known_id) and _model_has_embedding(connection, known_id, muq_run) and _model_has_embedding(connection, known_id, mert_run):
                    summary.already_linked += 1
                    continue
                audio = navidrome.audio_bytes(song.id)
                summary.downloaded += 1
                audio_hash = hashlib.sha256(audio).hexdigest()
                track_id, inserted = _upsert_track(connection, library_id, song, audio_hash)
                summary.inserted += int(inserted)
                waveform = decode_audio(audio)
                windows = deterministic_windows(waveform)
                del waveform
                if not _model_has_embedding(connection, track_id, muq_run):
                    _store_embedding(connection, track_id, muq_run, muq, windows)
                    summary.embedded_muq += 1
                else:
                    summary.reused_embeddings += 1
                if not _model_has_embedding(connection, track_id, mert_run):
                    _store_embedding(connection, track_id, mert_run, mert, windows)
                    summary.embedded_mert += 1
                else:
                    summary.reused_embeddings += 1
                if not _has_fingerprint(connection, track_id):
                    try:
                        with connection.transaction():
                            match = store_and_match_fingerprint(connection, track_id, audio, song.duration)
                        summary.fingerprinted += 1
                        summary.recording_matches += int(bool(match.get("matched")))
                    except Exception:
                        logger.exception("Could not fingerprint Navidrome song %s", song.id)
                del audio
                connection.commit()
            except Exception:
                connection.rollback()
                summary.failed += 1
                logger.exception("Failed to ingest Navidrome song %s", song.id)
            report({
                "phase": "processing", "message": f"Processed {song.title}",
                "completed": index + 1, "total": len(songs), "unit": "tracks", "summary": summary.__dict__,
            })

        report({"phase": "finalizing", "message": "Finalizing analysis runs", "completed": len(songs), "total": len(songs), "unit": "tracks"})
        with connection.cursor() as cursor:
            cursor.execute("UPDATE analysis_runs SET status='complete', finished_at=now() WHERE id = ANY(%s)", ([muq_run, mert_run],))
        connection.commit()
    return summary
