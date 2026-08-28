from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
import os
import platform
from pathlib import Path
import uuid

# The service package is read-only for its unprivileged runtime user. Numba must
# compile librosa's pitch helpers into a writable cache directory.
os.environ.setdefault("NUMBA_CACHE_DIR", f"/tmp/echora-numba-{os.getuid()}")
os.makedirs(os.environ["NUMBA_CACHE_DIR"], exist_ok=True)

import librosa
import numpy as np
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .audio import decode_audio
from .navidrome import NavidromeClient

CATALOG_SAMPLE_RATE = 44_100
QUERY_SAMPLE_RATE = 24_000
CONTOUR_HZ = 10
DEFAULT_CORPUS_SIZE = 50


def _smooth_pitch(pitch: np.ndarray, voiced: np.ndarray, radius: int = 2) -> np.ndarray:
    result = pitch.astype(np.float32, copy=True)
    for index in np.flatnonzero(voiced):
        left, right = max(0, index - radius), min(len(pitch), index + radius + 1)
        values = pitch[left:right][voiced[left:right]]
        if values.size:
            result[index] = np.median(values)
    return result


def _fill_short_gaps(pitch: np.ndarray, voiced: np.ndarray, maximum: int = 3) -> tuple[np.ndarray, np.ndarray]:
    pitch, voiced = pitch.copy(), voiced.copy()
    index = 0
    while index < len(voiced):
        if voiced[index]:
            index += 1
            continue
        end = index
        while end < len(voiced) and not voiced[end]:
            end += 1
        if index > 0 and end < len(voiced) and end - index <= maximum:
            pitch[index:end] = np.linspace(pitch[index - 1], pitch[end], end - index + 2)[1:-1]
            voiced[index:end] = True
        index = end
    return pitch, voiced


def _to_contour(pitch_hz: np.ndarray, voiced: np.ndarray, source_hz: float) -> tuple[np.ndarray, np.ndarray]:
    step = max(1, round(source_hz / CONTOUR_HZ))
    bins = int(np.ceil(len(pitch_hz) / step))
    pitch = np.zeros(bins, dtype=np.float32)
    mask = np.zeros(bins, dtype=bool)
    for index in range(bins):
        left, right = index * step, min(len(pitch_hz), (index + 1) * step)
        values = pitch_hz[left:right][voiced[left:right] & np.isfinite(pitch_hz[left:right]) & (pitch_hz[left:right] > 0)]
        if values.size:
            pitch[index] = float(np.median(69 + 12 * np.log2(values / 440.0)))
            mask[index] = True
    pitch, mask = _fill_short_gaps(pitch, mask)
    return _smooth_pitch(pitch, mask), mask


def extract_catalog_contour(audio: bytes) -> tuple[np.ndarray, np.ndarray]:
    from essentia.standard import EqualLoudness, PredominantPitchMelodia

    waveform = decode_audio(audio, CATALOG_SAMPLE_RATE)
    equalized = EqualLoudness(sampleRate=CATALOG_SAMPLE_RATE)(waveform)
    hop = 256
    pitch, confidence = PredominantPitchMelodia(
        sampleRate=CATALOG_SAMPLE_RATE, frameSize=2048, hopSize=hop,
        minFrequency=70, maxFrequency=1600,
    )(equalized)
    pitch = np.asarray(pitch, dtype=np.float32)
    confidence = np.asarray(confidence, dtype=np.float32)
    voiced = (pitch > 0) & np.isfinite(pitch) & (confidence > 0)
    return _to_contour(pitch, voiced, CATALOG_SAMPLE_RATE / hop)


def extract_hum_contour(audio: bytes) -> tuple[np.ndarray, np.ndarray]:
    waveform = decode_audio(audio, QUERY_SAMPLE_RATE)
    frame_length, hop = 2048, 240
    f0, voiced, probability = librosa.pyin(
        waveform, fmin=librosa.note_to_hz("C2"), fmax=librosa.note_to_hz("C7"),
        sr=QUERY_SAMPLE_RATE, frame_length=frame_length, hop_length=hop,
    )
    valid = voiced & np.isfinite(f0) & (probability >= 0.55)
    pitch, mask = _to_contour(np.nan_to_num(f0), valid, QUERY_SAMPLE_RATE / hop)
    indices = np.flatnonzero(mask)
    if indices.size == 0:
        raise ValueError("No stable hummed pitch was detected")
    pitch, mask = pitch[indices[0]:indices[-1] + 1], mask[indices[0]:indices[-1] + 1]
    if mask.sum() < 25:
        raise ValueError("Hum a clear melody for at least three seconds")
    return pitch, mask


def _relative(pitch: np.ndarray, voiced: np.ndarray) -> np.ndarray:
    result = pitch.astype(np.float32, copy=True)
    if voiced.any():
        result[voiced] -= np.median(result[voiced])
    return result


def _resample(values: np.ndarray, mask: np.ndarray, length: int) -> tuple[np.ndarray, np.ndarray]:
    source = np.arange(len(values), dtype=np.float32)
    target = np.linspace(0, max(0, len(values) - 1), length)
    filled = values.copy()
    known = np.flatnonzero(mask)
    if known.size < 2:
        return np.zeros(length, dtype=np.float32), np.zeros(length, dtype=bool)
    filled = np.interp(source, known, values[known])
    output = np.interp(target, source, filled).astype(np.float32)
    output_mask = np.interp(target, source, mask.astype(np.float32)) >= 0.5
    return output, output_mask


def _dtw_cost(query: np.ndarray, query_mask: np.ndarray, target: np.ndarray, target_mask: np.ndarray) -> float:
    query, target = _relative(query, query_mask), _relative(target, target_mask)
    rows, columns = len(query), len(target)
    costs = np.full((rows + 1, columns + 1), np.inf, dtype=np.float32)
    costs[0, 0] = 0
    for row in range(1, rows + 1):
        for column in range(1, columns + 1):
            if query_mask[row - 1] and target_mask[column - 1]:
                delta = abs(float(query[row - 1] - target[column - 1]))
                local = min(delta, 6.0) / 3.0
            elif query_mask[row - 1] == target_mask[column - 1]:
                local = 0.2
            else:
                local = 1.0
            costs[row, column] = local + min(costs[row - 1, column - 1], costs[row - 1, column] + 0.15, costs[row, column - 1] + 0.15)
    return float(costs[rows, columns] / max(rows, columns))


def match_contour(query: np.ndarray, query_mask: np.ndarray, target: np.ndarray, target_mask: np.ndarray) -> tuple[float, float]:
    """Return a lower-is-better cost and target offset in seconds."""
    query_length = len(query)
    best: tuple[float, int, np.ndarray, np.ndarray] | None = None
    for tempo in (0.75, 0.9, 1.0, 1.1, 1.25):
        width = max(20, round(query_length * tempo))
        if width > len(target):
            continue
        stride = max(1, CONTOUR_HZ // 2)
        for start in range(0, len(target) - width + 1, stride):
            candidate, candidate_mask = _resample(target[start:start + width], target_mask[start:start + width], query_length)
            overlap = query_mask & candidate_mask
            if overlap.sum() < query_mask.sum() * 0.55:
                continue
            q_relative, c_relative = _relative(query, overlap), _relative(candidate, overlap)
            delta = np.abs(q_relative[overlap] - c_relative[overlap])
            coarse = float(np.mean(np.minimum(delta, 6.0))) + float(1 - overlap.mean())
            if best is None or coarse < best[0]:
                best = (coarse, start, candidate, candidate_mask)
    if best is None:
        return float("inf"), 0.0
    return _dtw_cost(query, query_mask, best[2], best[3]), best[1] / CONTOUR_HZ


def _create_run(connection: psycopg.Connection, corpus_id: uuid.UUID) -> uuid.UUID:
    config = {"purpose": "hum_search", "corpus_id": str(corpus_id), "extractor": "essentia-melodia", "contour_hz": CONTOUR_HZ, "matcher": "relative-pitch-subsequence-dtw-v1"}
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    with connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO analysis_runs (kind,model_name,model_revision,config_hash,config,environment,device,precision,status,started_at)
               VALUES ('hum_corpus','melody_contour','melodia-2.1',%s,%s,%s,'cpu','float32','running',now()) RETURNING id""",
            (config_hash, Jsonb(config), Jsonb({"python": platform.python_version()})),
        )
        return cursor.fetchone()["id"]


def build_corpus(corpus_id: uuid.UUID, user_id: uuid.UUID, credentials: tuple[str, str, str], track_limit: int = DEFAULT_CORPUS_SIZE, progress: Callable[[dict[str, object]], None] | None = None) -> dict[str, int]:
    report = progress or (lambda _: None)
    completed = failed = 0
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection:
        run_id = _create_run(connection, corpus_id)
        with connection.cursor() as cursor:
            cursor.execute("UPDATE hum_corpora SET run_id=%s,status='building' WHERE id=%s AND user_id=%s", (run_id, corpus_id, user_id))
            cursor.execute("""SELECT DISTINCT ON (utl.track_id) utl.track_id,utl.external_id,t.title FROM user_track_links utl JOIN tracks t ON t.id=utl.track_id WHERE utl.user_id=%s ORDER BY utl.track_id""", (user_id,))
            candidates = cursor.fetchall()
        np.random.default_rng().shuffle(candidates)
        tracks = candidates[:track_limit]
        connection.commit()
        with NavidromeClient(*credentials) as client:
            for index, track in enumerate(tracks):
                report({"phase": "melody-index", "completed": index, "total": len(tracks), "message": f"Extracting melody from {track['title']}"})
                try:
                    pitch, voiced = extract_catalog_contour(client.audio_bytes(track["external_id"]))
                    if voiced.sum() < 30:
                        raise ValueError("No usable predominant melody")
                    with connection.cursor() as cursor:
                        cursor.execute("INSERT INTO hum_corpus_tracks (corpus_id,track_id) VALUES (%s,%s)", (corpus_id, track["track_id"]))
                        cursor.execute("""INSERT INTO melody_contours (track_id,run_id,source,hop_seconds,pitch,voiced) VALUES (%s,%s,'predominant-melody',%s,%s,%s)""", (track["track_id"], run_id, 1 / CONTOUR_HZ, pitch.tolist(), voiced.tolist()))
                    connection.commit(); completed += 1
                except Exception:
                    connection.rollback(); failed += 1
        with connection.cursor() as cursor:
            cursor.execute("UPDATE analysis_runs SET status='complete',finished_at=now() WHERE id=%s", (run_id,))
            cursor.execute("UPDATE hum_corpora SET status='complete',completed_at=now() WHERE id=%s", (corpus_id,))
        connection.commit()
    return {"tracks": completed, "failed": failed, "contours": completed}


def search_corpus(user_id: uuid.UUID, audio: bytes, limit: int = 10) -> dict[str, object]:
    query, query_mask = extract_hum_contour(audio)
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, connection.cursor() as cursor:
        cursor.execute("""SELECT mc.track_id,mc.pitch,mc.voiced FROM melody_contours mc JOIN hum_corpora hc ON hc.run_id=mc.run_id WHERE hc.user_id=%s AND hc.status='complete' AND hc.id=(SELECT hc2.id FROM hum_corpora hc2 JOIN melody_contours mc2 ON mc2.run_id=hc2.run_id WHERE hc2.user_id=%s AND hc2.status='complete' ORDER BY hc2.completed_at DESC LIMIT 1)""", (user_id, user_id))
        contours = cursor.fetchall()
        if not contours:
            raise ValueError("Build the melody hum index before searching")
        scored = []
        for row in contours:
            cost, offset = match_contour(query, query_mask, np.asarray(row["pitch"], dtype=np.float32), np.asarray(row["voiced"], dtype=bool))
            if np.isfinite(cost): scored.append((row["track_id"], cost, offset))
        scored.sort(key=lambda item: item[1]); selected = scored[:limit]
        if not selected:
            return {"tracks": [], "query_seconds": len(query) / CONTOUR_HZ}
        ids = [item[0] for item in selected]
        cursor.execute("""SELECT t.id,t.title,t.artist,t.album,t.duration_seconds,max(utl.external_id) source_id,max(ts.source_data->>'coverArt') cover_art FROM tracks t JOIN user_track_links utl ON utl.track_id=t.id AND utl.user_id=%s LEFT JOIN track_sources ts ON ts.library_id=utl.library_id AND ts.track_id=utl.track_id AND ts.external_id=utl.external_id WHERE t.id=ANY(%s) GROUP BY t.id""", (user_id, ids))
        metadata = {row["id"]: row for row in cursor.fetchall()}
    results = []
    for track_id, cost, offset in selected:
        row = dict(metadata[track_id]); row["similarity"] = float(np.exp(-cost)); row["matched_at_seconds"] = offset; row["match_cost"] = cost; results.append(row)

    diagnostic_id = str(uuid.uuid4())
    diagnostic_dir = Path(os.getenv("HUM_DIAGNOSTIC_DIR", "/tmp/echora-hum-debug")) / diagnostic_id
    diagnostic_dir.mkdir(parents=True, exist_ok=False)
    (diagnostic_dir / "recording.bin").write_bytes(audio)
    (diagnostic_dir / "diagnostic.json").write_text(json.dumps({
        "id": diagnostic_id,
        "user_id": str(user_id),
        "query_pitch": query.tolist(),
        "query_voiced": query_mask.tolist(),
        "query_seconds": len(query) / CONTOUR_HZ,
        "voiced_ratio": float(query_mask.mean()),
        "results": [{
            "track_id": str(row["id"]), "title": row["title"], "artist": row.get("artist"),
            "cost": row["match_cost"], "similarity": row["similarity"],
            "matched_at_seconds": row["matched_at_seconds"],
        } for row in results],
    }, ensure_ascii=False, indent=2))
    return {"tracks": results, "query_seconds": len(query) / CONTOUR_HZ, "matcher": "melody-contour-dtw-v1", "diagnostic_id": diagnostic_id}
