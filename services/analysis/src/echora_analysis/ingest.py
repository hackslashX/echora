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

from .audio import decode_audio, full_coverage_window_ranges
from .hum_search import create_sync_run, release_separator, store_track_contours
from .models import AudioEmbeddingModel, MertModel, MuQMuLanModel, release_model
from .navidrome import NavidromeClient, NavidromeTrack
from .processing_plan import plan_audio
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
    melody_indexed: int = 0
    melody_contours: int = 0
    recording_matches: int = 0
    failed: int = 0


def _vector_literal(vector: np.ndarray) -> str:
    return "[" + ",".join(f"{float(value):.9g}" for value in vector) + "]"


def _config_hash(value: dict[str, object]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _create_run(connection: psycopg.Connection, model: AudioEmbeddingModel) -> uuid.UUID:
    detailed = model.name in {"muq_mulan", "mert"}
    config = {
        "model": model.name,
        "revision": model.revision,
        "sample_rate": model.sample_rate,
        "coverage": "full-track" if detailed else "sampled",
        "windows": None if detailed else [0.15, 0.5, 0.85],
        "window_seconds": model.window_seconds,
        "stride_seconds": 5 if detailed else None,
        "aggregation": "normalized_mean",
        "store_window_embeddings": True,
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


def _store_embedding(
    connection: psycopg.Connection, track_id: uuid.UUID, run_id: uuid.UUID,
    model: AudioEmbeddingModel, windows: list[np.ndarray],
    ranges: list[tuple[float, float]] | None = None,
) -> None:
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
        cursor.executemany(
            """
            INSERT INTO embeddings
              (track_id, run_id, embedding_type, window_index, window_start_seconds,
               window_end_seconds, dimension, aggregation, embedding)
            VALUES (%s, %s, 'audio-window', %s, %s, %s, %s, 'none', %s::vector)
            ON CONFLICT (track_id, run_id, embedding_type, window_index) DO NOTHING
            """,
            [
                (
                    track_id, run_id, window_index,
                    ranges[window_index][0] if ranges else None,
                    ranges[window_index][1] if ranges else None,
                    len(vector), _vector_literal(vector),
                )
                for window_index, vector in enumerate(result.window_vectors)
            ],
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
    summary = IngestSummary(requested=len(song_ids))

    with psycopg.connect(os.environ["DATABASE_URL"]) as connection, NavidromeClient(
        url, username, password
    ) as navidrome:
        library_id = _library(connection, url)
        songs = navidrome.tracks(song_ids)
        summary.discovered = len(songs)
        plan = plan_audio(connection, library_id, [song.id for song in songs])
        required_models = int(plan.needs_muq) + int(plan.needs_mert)
        report({"phase": "planning", "message": "Processing plan ready", "completed": 0,
                "total": len(plan.download_external_ids), "unit": "tracks",
                "plan": {"muq": len(plan.muq_external_ids), "mert": len(plan.mert_external_ids),
                         "fingerprint": len(plan.fingerprint_external_ids),
                         "melody": len(plan.melody_external_ids)}})

        device = "cuda" if torch.cuda.is_available() else "cpu"
        downloaded_ids: set[str] = set()
        inserted_ids: set[uuid.UUID] = set()

        def audio_track(song: NavidromeTrack) -> tuple[bytes, uuid.UUID]:
            audio = navidrome.audio_bytes(song.id)
            if song.id not in downloaded_ids:
                downloaded_ids.add(song.id)
                summary.downloaded += 1
            track_id = _source_track_id(connection, library_id, song.id)
            if track_id is None:
                track_id, inserted = _upsert_track(
                    connection, library_id, song, hashlib.sha256(audio).hexdigest(),
                )
                if inserted and track_id not in inserted_ids:
                    inserted_ids.add(track_id)
                    summary.inserted += 1
            return audio, track_id

        def embedding_phase(
            phase: str, label: str, external_ids: frozenset[str], model: AudioEmbeddingModel,
        ) -> None:
            run_id = _create_run(connection, model)
            connection.commit()
            selected = [song for song in songs if song.id in external_ids]
            for index, song in enumerate(selected):
                report({
                    "phase": phase, "message": f"{label} {song.title}",
                    "track": {"id": song.id, "title": song.title, "artist": song.artist},
                    "completed": index, "total": len(selected), "unit": "tracks",
                    "summary": summary.__dict__,
                })
                try:
                    audio, track_id = audio_track(song)
                    waveform = decode_audio(audio)
                    ranged_windows = full_coverage_window_ranges(waveform)
                    windows = [item[0] for item in ranged_windows]
                    ranges = [(item[1], item[2]) for item in ranged_windows]
                    del waveform, audio
                    _store_embedding(connection, track_id, run_id, model, windows, ranges)
                    if phase == "muq":
                        summary.embedded_muq += 1
                    else:
                        summary.embedded_mert += 1
                    connection.commit()
                except Exception:
                    connection.rollback()
                    summary.failed += 1
                    logger.exception("Failed %s phase for Navidrome song %s", phase, song.id)
                report({
                    "phase": phase, "message": f"{label} {song.title}",
                    "completed": index + 1, "total": len(selected), "unit": "tracks",
                    "summary": summary.__dict__,
                })
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE analysis_runs SET status='complete', finished_at=now() WHERE id=%s",
                    (run_id,),
                )
            connection.commit()

        loaded = 0
        if plan.needs_muq:
            report({"phase": "models", "message": "Loading semantic model", "completed": loaded,
                    "total": required_models, "unit": "models"})
            muq = MuQMuLanModel(
                os.getenv("MUQ_MODEL_ID", "OpenMuQ/MuQ-MuLan-large"),
                os.getenv("MUQ_REVISION", "2e01c796b71dca71b45251384c04cd7b237c9020"),
                device,
            )
            try:
                embedding_phase("muq", "Embedding semantics for", plan.muq_external_ids, muq)
            finally:
                release_model(muq)
                del muq
            loaded += 1

        if plan.needs_mert:
            report({"phase": "models", "message": "Loading acoustic model", "completed": loaded,
                    "total": required_models, "unit": "models"})
            mert = MertModel(
                os.getenv("MERT_MODEL_ID", "m-a-p/MERT-v1-95M"),
                os.getenv("MERT_REVISION", "12af15fef9d0ac838c3f475bfbbf26d2060dd4f5"),
                device,
            )
            try:
                embedding_phase("mert", "Embedding acoustics for", plan.mert_external_ids, mert)
            finally:
                release_model(mert)
                del mert

        melody_songs = [song for song in songs if song.id in plan.melody_external_ids]
        if melody_songs:
            melody_run_id = create_sync_run(connection)
            connection.commit()
            try:
                for index, song in enumerate(melody_songs):
                    report({"phase": "melody", "message": f"Extracting melody from {song.title}",
                            "completed": index, "total": len(melody_songs), "unit": "tracks",
                            "summary": summary.__dict__})
                    try:
                        audio, track_id = audio_track(song)
                        summary.melody_contours += store_track_contours(connection, track_id, melody_run_id, audio)
                        summary.melody_indexed += 1
                        connection.commit()
                    except Exception:
                        connection.rollback()
                        summary.failed += 1
                        logger.exception("Could not extract melody for Navidrome song %s", song.id)
                    report({"phase": "melody", "message": f"Extracting melody from {song.title}",
                            "completed": index + 1, "total": len(melody_songs), "unit": "tracks",
                            "summary": summary.__dict__})
                with connection.cursor() as cursor:
                    cursor.execute("UPDATE analysis_runs SET status='complete',finished_at=now() WHERE id=%s", (melody_run_id,))
                connection.commit()
            finally:
                release_separator()

        fingerprint_songs = [song for song in songs if song.id in plan.fingerprint_external_ids]
        for index, song in enumerate(fingerprint_songs):
            report({
                "phase": "fingerprint", "message": f"Fingerprinting {song.title}",
                "track": {"id": song.id, "title": song.title, "artist": song.artist},
                "completed": index, "total": len(fingerprint_songs), "unit": "tracks",
                "summary": summary.__dict__,
            })
            try:
                audio, track_id = audio_track(song)
                with connection.transaction():
                    match = store_and_match_fingerprint(connection, track_id, audio, song.duration)
                summary.fingerprinted += 1
                summary.recording_matches += int(bool(match.get("matched")))
                del audio
                connection.commit()
            except Exception:
                connection.rollback()
                summary.failed += 1
                logger.exception("Could not fingerprint Navidrome song %s", song.id)
            report({
                "phase": "fingerprint", "message": f"Fingerprinting {song.title}",
                "completed": index + 1, "total": len(fingerprint_songs), "unit": "tracks",
                "summary": summary.__dict__,
            })

        summary.already_linked = len(songs) - len(plan.download_external_ids)
        report({"phase": "finalizing", "message": "Analysis phases complete",
                "completed": len(songs), "total": len(songs), "unit": "tracks"})
    return summary
