from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
import os
import platform
import uuid

import psycopg
from psycopg.types.json import Jsonb
import torch

from .lyrics_analysis import LyricsEmbeddingModel
from .navidrome import NavidromeClient


def _vector_literal(vector) -> str:
    return "[" + ",".join(f"{float(value):.9g}" for value in vector) + "]"


def _create_run(connection: psycopg.Connection, model: LyricsEmbeddingModel) -> uuid.UUID:
    config = {
        "model": model.name, "revision": model.revision, "chunk_tokens": model.chunk_tokens,
        "overlap_tokens": model.overlap_tokens, "aggregation": "normalized_mean",
        "pooling": "bge-m3 dense", "maximum_tokens": 8192,
    }
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    environment = {"python": platform.python_version(), "torch": torch.__version__, "cuda": torch.version.cuda}
    with connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO analysis_runs
                 (kind, model_name, model_revision, config_hash, config, environment, device, precision, status, started_at)
               VALUES ('lyrics_embedding',%s,%s,%s,%s,%s,%s,'float32','running',now())
               ON CONFLICT (kind, model_name, model_revision, config_hash)
               DO UPDATE SET status='running', started_at=now(), finished_at=NULL RETURNING id""",
            (model.name, model.revision, config_hash, Jsonb(config), Jsonb(environment), str(model.device)),
        )
        return cursor.fetchone()[0]


def _store_lyrics(connection: psycopg.Connection, track_id: uuid.UUID, result: dict[str, object]) -> uuid.UUID:
    text = result.get("text")
    status = str(result.get("status") or "unavailable")
    source = "embedded" if text else "none"
    with connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO lyrics (track_id, source, text, language, provenance, availability_status)
               VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (track_id) DO UPDATE SET source=EXCLUDED.source, text=EXCLUDED.text,
                 language=EXCLUDED.language, provenance=EXCLUDED.provenance,
                 availability_status=EXCLUDED.availability_status, created_at=now()
               RETURNING id""",
            (track_id, source, text, result.get("language"), Jsonb({
                "provider": "navidrome", "endpoint": result.get("source"),
                "synced": result.get("synced"), "lines": result.get("lines") or [],
            }), status),
        )
        return cursor.fetchone()[0]


def _store_embeddings(connection: psycopg.Connection, track_id: uuid.UUID, run_id: uuid.UUID, result) -> None:
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM embeddings WHERE track_id=%s AND run_id=%s AND embedding_type='lyrics'", (track_id, run_id))
        cursor.execute(
            """INSERT INTO embeddings
                 (track_id, run_id, embedding_type, dimension, aggregation, embedding, inference_ms, peak_vram_bytes)
               VALUES (%s,%s,'lyrics',%s,'normalized_mean',%s::vector,%s,%s)""",
            (track_id, run_id, len(result.aggregate), _vector_literal(result.aggregate), result.inference_ms, result.peak_vram_bytes),
        )
        for index, (vector, token_range) in enumerate(zip(result.windows, result.token_ranges)):
            cursor.execute(
                """INSERT INTO embeddings
                     (track_id, run_id, embedding_type, window_index, dimension, aggregation, embedding)
                   VALUES (%s,%s,'lyrics',%s,%s,%s,%s::vector)""",
                (track_id, run_id, index, len(vector), f"tokens:{token_range[0]}-{token_range[1]}", _vector_literal(vector)),
            )


def backfill_lyrics(
    url: str, username: str, password: str,
    progress: Callable[[dict[str, object]], None] | None = None,
    external_ids: list[str] | None = None,
    only_missing: bool = False,
) -> dict[str, int]:
    report = progress or (lambda _: None)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    report({"phase": "models", "message": "Loading BGE-M3 lyrics model", "completed": 3, "total": 4, "unit": "models"})
    model = LyricsEmbeddingModel(
        os.environ.get("LYRICS_MODEL_ID", "BAAI/bge-m3"),
        os.environ.get("LYRICS_REVISION", "5617a9f61b028005a4858fdac845db406aefb181"), device,
    )
    summary = {"total": 0, "available": 0, "missing": 0, "unavailable": 0, "embedded": 0, "failed": 0}
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection, NavidromeClient(url, username, password) as client:
        run_id = _create_run(connection, model)
        with connection.cursor() as cursor:
            clauses = ["ts.source_type='subsonic'"]
            parameters: list[object] = []
            if external_ids is not None:
                clauses.append("ts.external_id=ANY(%s)")
                parameters.append(external_ids)
            if only_missing:
                clauses.append(
                    "(l.track_id IS NULL OR NOT EXISTS (SELECT 1 FROM embeddings e JOIN analysis_runs ar ON ar.id=e.run_id "
                    "WHERE e.track_id=ts.track_id AND e.embedding_type='lyrics' AND e.window_index IS NULL AND ar.model_name='bge_m3'))"
                )
            cursor.execute(
                f"""SELECT DISTINCT ON (ts.track_id) ts.track_id, ts.external_id, t.title
                    FROM track_sources ts JOIN tracks t ON t.id=ts.track_id
                    LEFT JOIN lyrics l ON l.track_id=ts.track_id
                    WHERE {' AND '.join(clauses)} ORDER BY ts.track_id, ts.id""",
                parameters,
            )
            tracks = cursor.fetchall()
        summary["total"] = len(tracks)
        connection.commit()
        for index, (track_id, external_id, title) in enumerate(tracks):
            try:
                lyrics = client.lyrics(external_id)
                _store_lyrics(connection, track_id, lyrics)
                status = str(lyrics.get("status") or "unavailable")
                summary[status] = summary.get(status, 0) + 1
                if lyrics.get("text"):
                    embedded = model.embed(str(lyrics["text"]))
                    _store_embeddings(connection, track_id, run_id, embedded)
                    summary["embedded"] += 1
                connection.commit()
            except Exception:
                connection.rollback(); summary["failed"] += 1
            report({"phase": "lyrics", "message": f"Analyzing lyrics for {title}", "completed": index + 1,
                    "total": len(tracks), "unit": "tracks", "summary": summary})
        with connection.cursor() as cursor:
            cursor.execute("UPDATE analysis_runs SET status='complete', finished_at=now() WHERE id=%s", (run_id,))
        connection.commit()
    return summary
