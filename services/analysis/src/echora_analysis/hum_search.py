from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import platform
import threading
import uuid

# The service package is read-only for its unprivileged runtime user. Numba must
# compile librosa's pitch helpers into a writable cache directory.
os.environ.setdefault("NUMBA_CACHE_DIR", "/models/torch/numba")
os.makedirs(os.environ["NUMBA_CACHE_DIR"], exist_ok=True)

import librosa
import numpy as np
import psycopg
from psycopg.rows import dict_row, tuple_row
from psycopg.types.json import Jsonb

from .audio import decode_audio, decode_audio_channels
from .navidrome import NavidromeClient

CATALOG_SAMPLE_RATE = 44_100
QUERY_SAMPLE_RATE = 24_000
CONTOUR_HZ = 10
DEFAULT_CORPUS_SIZE = 50
_COARSE_STRIDE_SECONDS = 0.2
_DTW_CANDIDATES = 100
_REFINE_LIMIT = 600
_TEMPOS = (0.75, 0.9, 1.0, 1.1, 1.25)
_DEMUCS_MODEL = None
# Contours only change while a sync or corpus build is running. Caching the
# parsed arrays removes the per-query array decoding cost.
_CONTOUR_CACHE: dict[str, object] = {"key": None, "contours": ()}
_CACHE_LOCK = threading.Lock()


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


def extract_waveform_contour(waveform: np.ndarray, sample_rate: int) -> tuple[np.ndarray, np.ndarray]:
    from essentia.standard import EqualLoudness, PredominantPitchMelodia

    if sample_rate != CATALOG_SAMPLE_RATE:
        waveform = librosa.resample(waveform, orig_sr=sample_rate, target_sr=CATALOG_SAMPLE_RATE)
    waveform = np.ascontiguousarray(waveform, dtype=np.float32)
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


def extract_catalog_contour(audio: bytes) -> tuple[np.ndarray, np.ndarray]:
    return extract_waveform_contour(decode_audio(audio, CATALOG_SAMPLE_RATE), CATALOG_SAMPLE_RATE)


def separate_melody_sources(audio: bytes) -> dict[str, tuple[np.ndarray, int]]:
    global _DEMUCS_MODEL
    import torch
    from demucs import pretrained
    from demucs.apply import apply_model
    from demucs.audio import convert_audio

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if _DEMUCS_MODEL is None:
        _DEMUCS_MODEL = pretrained.get_model("htdemucs").eval().to(device)
    model = _DEMUCS_MODEL
    channels = decode_audio_channels(audio, CATALOG_SAMPLE_RATE, 2)
    waveform = torch.as_tensor(channels.T, dtype=torch.float32)
    waveform = convert_audio(waveform, CATALOG_SAMPLE_RATE, model.samplerate, model.audio_channels)
    reference = waveform.mean(0)
    mean, std = reference.mean(), reference.std().clamp_min(1e-8)
    with torch.inference_mode():
        sources = apply_model(
            model, ((waveform - mean) / std).unsqueeze(0), device=device,
            shifts=1, split=True, overlap=0.25, progress=False,
        )[0] * std + mean
    vocals = sources[model.sources.index("vocals")].mean(0).cpu().numpy()
    accompaniment = sources[[index for index, name in enumerate(model.sources) if name != "vocals"]].sum(0).mean(0).cpu().numpy()
    return {
        "vocals": (np.asarray(vocals, dtype=np.float32), int(model.samplerate)),
        "accompaniment": (np.asarray(accompaniment, dtype=np.float32), int(model.samplerate)),
    }


def release_separator() -> None:
    global _DEMUCS_MODEL
    if _DEMUCS_MODEL is None:
        return
    import gc
    import torch
    _DEMUCS_MODEL.to("cpu")
    _DEMUCS_MODEL = None
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def extract_hum_contour(audio: bytes) -> tuple[np.ndarray, np.ndarray]:
    waveform = decode_audio(audio, QUERY_SAMPLE_RATE)
    frame_length, hop = 2048, 480
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
    both_voiced = query_mask[:, None] & target_mask[None, :]
    both_unvoiced = ~query_mask[:, None] & ~target_mask[None, :]
    delta = np.minimum(np.abs(query[:, None] - target[None, :]), 6.0) / 3.0
    local = np.where(both_voiced, delta, np.where(both_unvoiced, 0.2, 1.0)).astype(np.float32)
    accumulated = librosa.sequence.dtw(C=local, backtrack=False)
    return float(accumulated[-1, -1] / max(len(query), len(target)))


def _coarse_scores(query: np.ndarray, query_mask: np.ndarray, target: np.ndarray,
                   target_mask: np.ndarray, indices: np.ndarray) -> np.ndarray:
    """Score every window. Lower is better; inf marks unusable windows."""
    candidates = target[indices]
    candidate_masks = target_mask[indices]
    overlaps = candidate_masks & query_mask[None, :]
    voiced_counts = overlaps.sum(axis=1)
    valid = voiced_counts >= query_mask.sum() * 0.55
    safe_overlaps = overlaps.copy()
    safe_overlaps[~valid, 0] = True
    q_values = np.where(safe_overlaps, query[None, :], np.nan)
    c_values = np.where(safe_overlaps, candidates, np.nan)
    q_relative = query[None, :] - np.nanmedian(q_values, axis=1)[:, None]
    c_relative = candidates - np.nanmedian(c_values, axis=1)[:, None]
    deltas = np.minimum(np.abs(q_relative - c_relative), 6.0)
    coarse = np.divide(
        np.where(overlaps, deltas, 0).sum(axis=1), voiced_counts,
        out=np.full(len(indices), np.inf), where=voiced_counts > 0,
    ) + (1 - overlaps.mean(axis=1))
    coarse[~valid] = np.inf
    return coarse


def _coarse_half(query: np.ndarray, query_mask: np.ndarray, target: np.ndarray,
                 target_mask: np.ndarray) -> tuple[float, int, float] | None:
    """Quarter-resolution scan over every tempo in one vectorized pass.

    Returns the best (score, full-resolution center frame, tempo). The scan only
    has to locate candidate regions; refinement and DTW confirm at full
    resolution afterwards.
    """
    quarter_query, quarter_mask = query[::4], query_mask[::4]
    quarter_target, quarter_target_mask = target[::4], target_mask[::4]
    plans: list[tuple[np.ndarray, np.ndarray, int, int, float]] = []
    for tempo in _TEMPOS:
        width = max(5, round(len(quarter_query) * tempo))
        if width > len(quarter_target):
            continue
        starts = np.arange(0, len(quarter_target) - width + 1, 1)
        offsets = np.rint(np.linspace(0, width - 1, len(quarter_query))).astype(int)
        plans.append((starts, offsets, len(starts), width, tempo))
    if not plans:
        return None
    common = max(plan[3] for plan in plans)
    # Pad every tempo to the widest window so one gather and one scoring call
    # cover all blocks. Padded columns point at frame zero but their query mask
    # is False, so they never enter overlap or cost math.
    padded_query = np.concatenate([quarter_query, np.zeros(common - len(quarter_query), np.float32)])
    padded_mask = np.concatenate([quarter_mask, np.zeros(common - len(quarter_mask), dtype=bool)])
    padded_offsets = np.zeros(common, dtype=int)
    indices = np.vstack([
        starts[:, None] + np.concatenate([offsets, padded_offsets[len(offsets):]])[None, :]
        for starts, offsets, _, _, _ in plans
    ])
    scores = _coarse_scores(padded_query, padded_mask, quarter_target, quarter_target_mask, indices)
    index = int(np.argmin(scores))
    if not np.isfinite(scores[index]):
        return None
    for starts, _, count, _, tempo in plans:
        if index < count:
            return float(scores[index]), int(starts[index]) * 4, tempo
        index -= count
    return None


def _refine(query: np.ndarray, query_mask: np.ndarray, target: np.ndarray, target_mask: np.ndarray,
            center: int, tempo: float) -> tuple[float, int, np.ndarray, np.ndarray] | None:
    """Full-resolution scan around a 5 Hz candidate center."""
    query_length = len(query)
    full_width = max(20, round(query_length * tempo))
    low = max(0, center - 12)
    high = min(len(target) - full_width, center + 12)
    if high < low:
        return None
    starts = np.arange(low, high + 1)
    offsets = np.rint(np.linspace(0, full_width - 1, query_length)).astype(int)
    scores = _coarse_scores(query, query_mask, target, target_mask, starts[:, None] + offsets[None, :])
    index = int(np.argmin(scores))
    if not np.isfinite(scores[index]):
        return None
    start = int(starts[index])
    return float(scores[index]), start, target[start:start + full_width], target_mask[start:start + full_width]


def match_contour(query: np.ndarray, query_mask: np.ndarray, target: np.ndarray, target_mask: np.ndarray) -> tuple[float, float]:
    """Return a lower-is-better cost and target offset in seconds."""
    half = _coarse_half(query, query_mask, target, target_mask)
    if half is None:
        return float("inf"), 0.0
    best = _refine(query, query_mask, target, target_mask, half[1], half[2])
    if best is None:
        return float("inf"), 0.0
    return _dtw_cost(query, query_mask, best[2], best[3]), best[1] / CONTOUR_HZ


def _create_run(connection: psycopg.Connection, corpus_id: uuid.UUID) -> uuid.UUID:
    config = {"purpose": "hum_search", "corpus_id": str(corpus_id), "extractor": "demucs-htdemucs-plus-essentia-melodia", "sources": ["full-mix", "vocals", "accompaniment"], "contour_hz": CONTOUR_HZ, "matcher": "relative-pitch-subsequence-dtw-v1"}
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    with connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO analysis_runs (kind,model_name,model_revision,config_hash,config,environment,device,precision,status,started_at)
               VALUES ('hum_corpus','melody_contour','melodia-2.1',%s,%s,%s,'cpu','float32','running',now()) RETURNING id""",
            (config_hash, Jsonb(config), Jsonb({"python": platform.python_version()})),
        )
        return cursor.fetchone()["id"]


def create_sync_run(connection: psycopg.Connection) -> uuid.UUID:
    config = {"extractor": "demucs-htdemucs-plus-essentia-melodia", "sources": ["full-mix", "vocals", "accompaniment"], "contour_hz": CONTOUR_HZ}
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    with connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO analysis_runs (kind,model_name,model_revision,config_hash,config,environment,device,precision,status,started_at)
               VALUES ('melody_contour','melody_contour','multi-source-v1',%s,%s,%s,'mixed','float32','running',now())
               ON CONFLICT (kind,model_name,model_revision,config_hash)
               DO UPDATE SET status='running',started_at=now(),finished_at=NULL RETURNING id""",
            (config_hash, Jsonb(config), Jsonb({"python": platform.python_version()})),
        )
        row = cursor.fetchone()
        return row["id"] if isinstance(row, dict) else row[0]


def store_track_contours(connection: psycopg.Connection, track_id: uuid.UUID, run_id: uuid.UUID, audio: bytes) -> int:
    sources: dict[str, tuple[np.ndarray, np.ndarray]] = {"full-mix": extract_catalog_contour(audio)}
    try:
        for source, (waveform, sample_rate) in separate_melody_sources(audio).items():
            sources[source] = extract_waveform_contour(waveform, sample_rate)
    except Exception:
        pass
    usable = {source: contour for source, contour in sources.items() if contour[1].sum() >= 30}
    if not usable:
        raise ValueError("No usable melody source")
    with connection.cursor() as cursor:
        for source, (pitch, voiced) in usable.items():
            cursor.execute(
                """INSERT INTO melody_contours (track_id,run_id,source,hop_seconds,pitch,voiced)
                   VALUES (%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (track_id,run_id,source) DO UPDATE
                   SET hop_seconds=EXCLUDED.hop_seconds,pitch=EXCLUDED.pitch,voiced=EXCLUDED.voiced""",
                (track_id, run_id, source, 1 / CONTOUR_HZ, pitch.tolist(), voiced.tolist()),
            )
    return len(usable)


def build_corpus(corpus_id: uuid.UUID, user_id: uuid.UUID, credentials: tuple[str, str, str], track_limit: int = DEFAULT_CORPUS_SIZE, progress: Callable[[dict[str, object]], None] | None = None, track_ids: set[uuid.UUID] | None = None) -> dict[str, int]:
    report = progress or (lambda _: None)
    completed = failed = contours_stored = 0
    try:
        with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection:
            run_id = _create_run(connection, corpus_id)
            with connection.cursor() as cursor:
                cursor.execute("UPDATE hum_corpora SET run_id=%s,status='building' WHERE id=%s AND user_id=%s", (run_id, corpus_id, user_id))
                cursor.execute("""SELECT DISTINCT ON (utl.track_id) utl.track_id,utl.external_id,t.title FROM user_track_links utl JOIN tracks t ON t.id=utl.track_id WHERE utl.user_id=%s ORDER BY utl.track_id""", (user_id,))
                candidates = cursor.fetchall()
            if track_ids is not None:
                tracks = [track for track in candidates if track["track_id"] in track_ids][:track_limit]
            else:
                np.random.default_rng().shuffle(candidates)
                tracks = candidates[:track_limit]
            connection.commit()
            with NavidromeClient(*credentials) as client:
                for index, track in enumerate(tracks):
                    report({"phase": "melody-index", "completed": index, "total": len(tracks), "message": f"Separating melody sources for {track['title']}"})
                    try:
                        audio = client.audio_bytes(track["external_id"])
                        sources: dict[str, tuple[np.ndarray, np.ndarray]] = {
                            "full-mix": extract_catalog_contour(audio),
                        }
                        try:
                            for source, (waveform, sample_rate) in separate_melody_sources(audio).items():
                                sources[source] = extract_waveform_contour(waveform, sample_rate)
                        except Exception:
                            # Keep the full-mix contour when separation fails for one recording.
                            pass
                        usable = {source: contour for source, contour in sources.items() if contour[1].sum() >= 30}
                        if not usable:
                            raise ValueError("No usable melody source")
                        with connection.cursor() as cursor:
                            cursor.execute("INSERT INTO hum_corpus_tracks (corpus_id,track_id) VALUES (%s,%s)", (corpus_id, track["track_id"]))
                            for source, (pitch, voiced) in usable.items():
                                cursor.execute("""INSERT INTO melody_contours (track_id,run_id,source,hop_seconds,pitch,voiced) VALUES (%s,%s,%s,%s,%s,%s)""", (track["track_id"], run_id, source, 1 / CONTOUR_HZ, pitch.tolist(), voiced.tolist()))
                        connection.commit(); completed += 1; contours_stored += len(usable)
                    except Exception:
                        connection.rollback(); failed += 1
            with connection.cursor() as cursor:
                cursor.execute("UPDATE analysis_runs SET status='complete',finished_at=now() WHERE id=%s", (run_id,))
                cursor.execute("UPDATE hum_corpora SET status='complete',completed_at=now() WHERE id=%s", (corpus_id,))
            connection.commit()
        return {"tracks": completed, "failed": failed, "contours": contours_stored}
    finally:
        release_separator()


def _contour_cache_key(connection: psycopg.Connection) -> tuple[int, str] | None:
    with connection.cursor(row_factory=tuple_row) as cursor:
        cursor.execute("SELECT count(*),coalesce(max(track_id::text),'') FROM melody_contours")
        row = cursor.fetchone()
    count, latest = row
    return int(count), str(latest or "")


def _load_contours(connection: psycopg.Connection, user_id: uuid.UUID) -> list[dict[str, object]]:
    key = _contour_cache_key(connection)
    with _CACHE_LOCK:
        if _CONTOUR_CACHE["key"] == key and _CONTOUR_CACHE["contours"]:
            return _CONTOUR_CACHE["contours"]  # type: ignore[return-value]
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """SELECT DISTINCT ON (mc.track_id,mc.source)
                          mc.track_id,mc.source,mc.pitch,mc.voiced
                   FROM melody_contours mc JOIN analysis_runs ar ON ar.id=mc.run_id
                   WHERE ar.status IN ('complete','running')
                     AND EXISTS (SELECT 1 FROM user_track_links utl
                                 WHERE utl.user_id=%s AND utl.track_id=mc.track_id)
                   ORDER BY mc.track_id,mc.source,ar.created_at DESC""",
                (user_id,),
            )
            rows = cursor.fetchall()
        contours = [
            {**row, "pitch": np.asarray(row["pitch"], dtype=np.float32),
             "voiced": np.asarray(row["voiced"], dtype=bool)}
            for row in rows
        ]
        _CONTOUR_CACHE["key"] = key
        _CONTOUR_CACHE["contours"] = contours
        return contours


def search_corpus(user_id: uuid.UUID, audio: bytes, limit: int = 10) -> dict[str, object]:
    query, query_mask = extract_hum_contour(audio)
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection:
        contours = _load_contours(connection, user_id)
        if not contours:
            raise ValueError("Build the melody hum index before searching")

        def scan_half(contour: dict[str, object]) -> tuple[float, int, float, dict[str, object]] | None:
            half = _coarse_half(query, query_mask, contour["pitch"], contour["voiced"])
            if half is None:
                return None
            return (*half, contour)

        workers = min(16, (os.cpu_count() or 2))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            scanned = [item for item in pool.map(scan_half, contours) if item is not None]
        if not scanned:
            return {"tracks": [], "query_seconds": len(query) / CONTOUR_HZ}
        # Refinement and DTW only make sense for plausible contenders. Everything
        # far worse than the global leader cannot reach the result list.
        scanned.sort(key=lambda item: item[0])
        contenders = scanned[:_REFINE_LIMIT]

        def refine(item: tuple[float, int, float, dict[str, object]]) -> tuple[float, int, np.ndarray, np.ndarray, dict[str, object]] | None:
            _, center, tempo, contour = item
            best = _refine(query, query_mask, contour["pitch"], contour["voiced"], center, tempo)
            if best is None:
                return None
            return (*best, contour)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            refined = [item for item in pool.map(refine, contenders) if item is not None]
        refined.sort(key=lambda item: item[0])
        finalists = refined[:_DTW_CANDIDATES]

        def confirm(item: tuple[float, int, np.ndarray, np.ndarray, dict[str, object]]) -> tuple[float, float, str, uuid.UUID]:
            _, start, candidate, candidate_mask, contour = item
            cost = _dtw_cost(query, query_mask, candidate, candidate_mask)
            return cost, start / CONTOUR_HZ, str(contour["source"]), contour["track_id"]

        with ThreadPoolExecutor(max_workers=workers) as pool:
            confirmed = list(pool.map(confirm, finalists))
        best_by_track: dict[uuid.UUID, tuple[float, float, str]] = {}
        for cost, offset, source, track_id in confirmed:
            if not np.isfinite(cost):
                continue
            current = best_by_track.get(track_id)
            if current is None or cost < current[0]:
                best_by_track[track_id] = (cost, offset, source)
        scored = [(track_id, *match) for track_id, match in best_by_track.items()]
        scored.sort(key=lambda item: item[1])
        selected = scored[:limit]
        if not selected:
            return {"tracks": [], "query_seconds": len(query) / CONTOUR_HZ}
        ids = [item[0] for item in selected]
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """SELECT t.id,t.title,t.artist,t.album,t.duration_seconds,max(utl.external_id) source_id,
                          max(ts.source_data->>'coverArt') cover_art
                   FROM tracks t JOIN user_track_links utl ON utl.track_id=t.id AND utl.user_id=%s
                   LEFT JOIN track_sources ts ON ts.library_id=utl.library_id AND ts.track_id=utl.track_id
                                              AND ts.external_id=utl.external_id
                   WHERE t.id=ANY(%s) GROUP BY t.id""",
                (user_id, ids),
            )
            metadata = {row["id"]: row for row in cursor.fetchall()}
    results = []
    for track_id, cost, offset, source in selected:
        row = dict(metadata[track_id])
        row.update(similarity=float(np.exp(-cost)), matched_at_seconds=offset, match_cost=cost, matched_source=source)
        results.append(row)
    return {
        "tracks": results, "query_seconds": len(query) / CONTOUR_HZ,
        "matcher": "parallel-two-resolution-melody-dtw-v5",
        "candidate_contours": len(contours), "dtw_finalists": len(finalists),
    }
