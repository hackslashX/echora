from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
import os
import platform
import uuid

import numpy as np
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import torch

from .audio import decode_audio
from .models import MertModel, release_model
from .navidrome import NavidromeClient

WINDOW_SECONDS = 10
STRIDE_SECONDS = 5
DEFAULT_CORPUS_SIZE = 50


def _vector_literal(vector: np.ndarray) -> str:
    return "[" + ",".join(f"{float(value):.9g}" for value in vector) + "]"


def overlapping_windows(waveform: np.ndarray, sample_rate: int = 24_000) -> list[tuple[float, float, np.ndarray]]:
    size = sample_rate * WINDOW_SECONDS
    stride = sample_rate * STRIDE_SECONDS
    if waveform.size <= size:
        padded = np.pad(waveform, (0, max(0, size - waveform.size)))
        return [(0.0, waveform.size / sample_rate, padded.astype(np.float32))]
    starts = list(range(0, waveform.size - size + 1, stride))
    final = waveform.size - size
    if starts[-1] != final:
        starts.append(final)
    return [
        (start / sample_rate, (start + size) / sample_rate,
         np.ascontiguousarray(waveform[start:start + size], dtype=np.float32))
        for start in starts
    ]


def _create_run(connection: psycopg.Connection, corpus_id: uuid.UUID, model: MertModel) -> uuid.UUID:
    config = {
        "purpose": "experimental_hum_search",
        "corpus_id": str(corpus_id),
        "sample_rate": model.sample_rate,
        "window_seconds": WINDOW_SECONDS,
        "stride_seconds": STRIDE_SECONDS,
        "pooling": "final_hidden_state_mean",
    }
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    with connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO analysis_runs
                 (kind, model_name, model_revision, config_hash, config, environment,
                  device, precision, status, started_at)
               VALUES ('hum_corpus', 'mert', %s, %s, %s, %s, %s, 'float32', 'running', now())
               RETURNING id""",
            (model.revision, config_hash, Jsonb(config), Jsonb({"python": platform.python_version(), "torch": torch.__version__}), str(model.device)),
        )
        return cursor.fetchone()["id"]


def build_corpus(
    corpus_id: uuid.UUID,
    user_id: uuid.UUID,
    credentials: tuple[str, str, str],
    track_limit: int = DEFAULT_CORPUS_SIZE,
    progress: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, int]:
    report = progress or (lambda _: None)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = MertModel(
        os.getenv("MERT_MODEL_ID", "m-a-p/MERT-v1-95M"),
        os.getenv("MERT_REVISION", "main"), device,
    )
    completed = failed = windows_stored = 0
    try:
        with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection:
            run_id = _create_run(connection, corpus_id, model)
            with connection.cursor() as cursor:
                cursor.execute(
                    """UPDATE hum_corpora SET run_id=%s, status='building' WHERE id=%s AND user_id=%s""",
                    (run_id, corpus_id, user_id),
                )
                cursor.execute(
                    """SELECT DISTINCT ON (utl.track_id) utl.track_id, utl.external_id, t.title
                       FROM user_track_links utl JOIN tracks t ON t.id=utl.track_id
                       WHERE utl.user_id=%s ORDER BY utl.track_id, random()""",
                    (user_id,),
                )
                candidates = cursor.fetchall()
            # Sampling in Python avoids PostgreSQL DISTINCT ON ordering constraints.
            rng = np.random.default_rng()
            rng.shuffle(candidates)
            tracks = candidates[:track_limit]
            connection.commit()
            with NavidromeClient(*credentials) as client:
                for index, track in enumerate(tracks):
                    report({"phase": "hum-index", "completed": index, "total": len(tracks), "message": f"Indexing {track['title']}"})
                    try:
                        waveform = decode_audio(client.audio_bytes(track["external_id"]))
                        windows = overlapping_windows(waveform)
                        vectors = model.embed_each([item[2] for item in windows])
                        with connection.cursor() as cursor:
                            cursor.execute(
                                "INSERT INTO hum_corpus_tracks (corpus_id, track_id) VALUES (%s,%s)",
                                (corpus_id, track["track_id"]),
                            )
                            for window_index, ((start, end, _), vector) in enumerate(zip(windows, vectors)):
                                cursor.execute(
                                    """INSERT INTO embeddings
                                         (track_id, run_id, embedding_type, window_index, window_start_seconds,
                                          window_end_seconds, dimension, aggregation, embedding)
                                       VALUES (%s,%s,'audio-window',%s,%s,%s,%s,'mert-frame-mean',%s::vector)""",
                                    (track["track_id"], run_id, window_index, start, end, len(vector), _vector_literal(vector)),
                                )
                        connection.commit()
                        completed += 1
                        windows_stored += len(vectors)
                    except Exception:
                        connection.rollback()
                        failed += 1
            with connection.cursor() as cursor:
                cursor.execute("UPDATE analysis_runs SET status='complete', finished_at=now() WHERE id=%s", (run_id,))
                cursor.execute("UPDATE hum_corpora SET status='complete', completed_at=now() WHERE id=%s", (corpus_id,))
            connection.commit()
        return {"tracks": completed, "failed": failed, "windows": windows_stored}
    finally:
        release_model(model)


def search_corpus(user_id: uuid.UUID, audio: bytes, limit: int = 10) -> dict[str, object]:
    waveform = decode_audio(audio)
    query_window = overlapping_windows(waveform)[0][2]
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = MertModel(os.getenv("MERT_MODEL_ID", "m-a-p/MERT-v1-95M"), os.getenv("MERT_REVISION", "main"), device)
    try:
        query = model.embed_each([query_window])[0]
    finally:
        release_model(model)
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, connection.cursor() as cursor:
        cursor.execute(
            """WITH corpus AS (
                 SELECT id, run_id FROM hum_corpora
                 WHERE user_id=%s AND status='complete' ORDER BY completed_at DESC LIMIT 1
               ), ranked_windows AS (
                 SELECT e.track_id, e.window_start_seconds, 1 - (e.embedding <=> %s::vector) AS similarity,
                        row_number() OVER (PARTITION BY e.track_id ORDER BY e.embedding <=> %s::vector) AS track_rank
                 FROM corpus c JOIN embeddings e ON e.run_id=c.run_id
                 JOIN hum_corpus_tracks hct ON hct.corpus_id=c.id AND hct.track_id=e.track_id
                 WHERE e.embedding_type='audio-window'
               )
               SELECT t.id, t.title, t.artist, t.album, t.duration_seconds,
                      rw.similarity, rw.window_start_seconds AS matched_at_seconds,
                      max(utl.external_id) AS source_id,
                      max(ts.source_data->>'coverArt') AS cover_art
               FROM ranked_windows rw JOIN tracks t ON t.id=rw.track_id
               JOIN user_track_links utl ON utl.track_id=t.id AND utl.user_id=%s
               LEFT JOIN track_sources ts ON ts.library_id=utl.library_id AND ts.track_id=utl.track_id
                                           AND ts.external_id=utl.external_id
               WHERE rw.track_rank=1
               GROUP BY t.id, rw.similarity, rw.window_start_seconds
               ORDER BY rw.similarity DESC LIMIT %s""",
            (user_id, _vector_literal(query), _vector_literal(query), user_id, limit),
        )
        rows = cursor.fetchall()
    return {"tracks": rows, "query_seconds": waveform.size / 24_000}
