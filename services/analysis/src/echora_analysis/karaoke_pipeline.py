from __future__ import annotations

from collections.abc import Callable
import json
import logging
import os
from pathlib import Path
import re
import selectors
import subprocess
import statistics
import sys
import tempfile
import threading
import uuid

import psycopg
from psycopg.types.json import Jsonb

from .navidrome import NavidromeClient
from .processing_plan import plan_karaoke

logger = logging.getLogger(__name__)

FA_KARA_REVISION = "168ca5f01cecaa1290e31c0ce8dc44af8c7451bb"
KARAOKE_PIPELINE_REVISION = "v1"
DEFAULT_MODEL_ID = "NextFire/mms-300m-ForcedAligner-karaoke-ja-Latn"
DEFAULT_MODEL_REVISION = "2ab2b5f46539ee284703c281f286b01d2410ee12"
_DIALOGUE = re.compile(r"^Dialogue: [^,]*,([^,]+),([^,]+),(?:[^,]*,){6}(.*)$")
_KARAOKE_TAG = re.compile(r"\{\\k(\d+)\}")
_ASS_TAG = re.compile(r"\{[^}]*\}")
_KARAOKE_LOCK = threading.Lock()
_FA_KARA_WORKER: subprocess.Popen[str] | None = None
_FA_KARA_WORKER_KEY: tuple[str, str] | None = None


def _ass_time_ms(value: str) -> int:
    hours, minutes, seconds = value.split(":")
    return round((int(hours) * 3600 + int(minutes) * 60 + float(seconds)) * 1000)


def parse_ass_karaoke(ass: str) -> list[dict[str, object]]:
    """Convert FA-Kara ASS dialogue into line and syllable timing for the API."""
    lines: list[dict[str, object]] = []
    for raw_line in ass.splitlines():
        match = _DIALOGUE.match(raw_line)
        if not match:
            continue
        start_ms = _ass_time_ms(match.group(1))
        end_ms = _ass_time_ms(match.group(2))
        body = match.group(3)
        cursor_ms = start_ms
        syllables: list[dict[str, object]] = []
        parts = _KARAOKE_TAG.split(body)
        prefix = _ASS_TAG.sub("", parts[0])
        text_parts = [prefix] if prefix else []
        for index in range(1, len(parts), 2):
            duration_ms = int(parts[index]) * 10
            text = _ASS_TAG.sub("", parts[index + 1] if index + 1 < len(parts) else "")
            if text:
                syllables.append({"start_ms": cursor_ms, "end_ms": cursor_ms + duration_ms, "text": text})
                text_parts.append(text)
            cursor_ms += duration_ms
        text = "".join(text_parts).replace("#|", "").replace("|<", "")
        lines.append({"start_ms": start_ms, "end_ms": end_ms, "text": text, "syllables": syllables})
    return lines


def _line_key(text: object) -> str:
    return re.sub(r"[^\w]+", "", str(text or "").casefold())


def stabilize_to_synced_lines(karaoke: list[dict[str, object]], source: list[dict[str, object]]) -> list[dict[str, object]]:
    """Prevent an independently aligned block from activating mid-line."""
    timed_source = _timed_source_lines(source)
    source_index = 0
    stabilized: list[dict[str, object]] = []
    for line in karaoke:
        key = _line_key(line.get("text"))
        match_index = next((index for index in range(source_index, len(timed_source))
                            if _line_key(timed_source[index].get("text")) == key), -1)
        if match_index < 0:
            stabilized.append(line)
            continue
        source_index = match_index + 1
        source_start = int(timed_source[match_index]["start_ms"])
        syllables = list(line.get("syllables") or [])
        first_start = int(syllables[0]["start_ms"]) if syllables else source_start
        shift = max(0, source_start - first_start)
        shifted_syllables = [
            {**syllable, "start_ms": int(syllable["start_ms"]) + shift,
             "end_ms": int(syllable["end_ms"]) + shift}
            for syllable in syllables
        ]
        stabilized.append({
            **line,
            "start_ms": max(source_start, int(line.get("start_ms") or source_start) + shift),
            "end_ms": max(source_start, int(line.get("end_ms") or source_start) + shift),
            "syllables": shifted_syllables,
        })
    return stabilized


def guard_pathological_lead_ins(
    karaoke: list[dict[str, object]], source: list[dict[str, object]], diagnostics: dict[str, object],
) -> list[dict[str, object]]:
    """Delay only first syllables that absorb seconds of pre-vocal audio."""
    source_lines = _anchored_source_lines(source)
    offset = float(diagnostics.get("source_offset_ms", 0))
    slope = 1.0 + float(diagnostics.get("source_drift_ms_per_minute", 0)) / 60000.0
    guarded = []
    guarded_indexes = []
    for index, line in enumerate(karaoke):
        syllables = [dict(item) for item in line.get("syllables") or []]
        if index >= len(source_lines) or not syllables:
            guarded.append(line)
            continue
        first = syllables[0]
        duration = int(first["end_ms"]) - int(first["start_ms"])
        source_start = round(float(source_lines[index]["start_ms"]) * slope + offset)
        if duration <= 1200 or source_start < int(first["start_ms"]) + 1000 or source_start > int(first["end_ms"]) + 500:
            guarded.append(line)
            continue
        first["start_ms"] = source_start
        first["end_ms"] = max(int(first["end_ms"]), source_start + 100)
        previous_end = int(first["end_ms"])
        for syllable in syllables[1:]:
            syllable["start_ms"] = max(int(syllable["start_ms"]), previous_end)
            syllable["end_ms"] = max(int(syllable["end_ms"]), int(syllable["start_ms"]))
            previous_end = int(syllable["end_ms"])
        guarded.append({**line, "start_ms": max(int(line.get("start_ms") or 0), source_start - 200),
                        "end_ms": max(int(line.get("end_ms") or 0), previous_end), "syllables": syllables})
        guarded_indexes.append(index)
    diagnostics["pathological_lead_in_guarded_lines"] = guarded_indexes
    return guarded


def bound_to_synced_lines(karaoke: list[dict[str, object]], source: list[dict[str, object]]) -> list[dict[str, object]]:
    """Keep each aligned line inside its matching source line window."""
    timed_source = [line for line in source if str(line.get("text") or "").strip() and isinstance(line.get("start_ms"), (int, float))]
    source_index = 0
    bounded: list[dict[str, object]] = []
    for line in karaoke:
        key = _line_key(line.get("text"))
        match_index = next((index for index in range(source_index, len(timed_source)) if _line_key(timed_source[index].get("text")) == key), -1)
        if match_index < 0:
            bounded.append(line)
            continue
        source_index = match_index + 1
        window_start = int(timed_source[match_index]["start_ms"])
        window_end = int(timed_source[match_index + 1]["start_ms"]) if match_index + 1 < len(timed_source) else int(line.get("end_ms") or window_start)
        if window_end < window_start:
            window_end = window_start
        syllables = []
        for syllable in line.get("syllables") or []:
            start = min(window_end, max(window_start, int(syllable["start_ms"])))
            end = min(window_end, max(start, int(syllable["end_ms"])))
            syllables.append({**syllable, "start_ms": start, "end_ms": end})
        bounded.append({**line, "start_ms": window_start, "end_ms": window_end, "syllables": syllables})
    return bounded


def _timed_source_lines(source: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {"text": str(line.get("text") or "").strip(), "start_ms": int(line["start_ms"])}
        for line in source
        if str(line.get("text") or "").strip() and isinstance(line.get("start_ms"), (int, float))
    ]


def _anchored_source_lines(source: list[dict[str, object]]) -> list[dict[str, object]]:
    """Preserve every lyric line and interpolate timestamps missing in source."""
    lines = [
        {"text": str(line.get("text") or "").strip(), "start_ms": line.get("start_ms")}
        for line in source if str(line.get("text") or "").strip()
    ]
    known = [index for index, line in enumerate(lines) if isinstance(line["start_ms"], (int, float))]
    if not known:
        return []
    known_gaps = [
        (float(lines[right]["start_ms"]) - float(lines[left]["start_ms"])) / (right - left)
        for left, right in zip(known, known[1:]) if right > left
    ]
    fallback_gap = max(500.0, statistics.median(known_gaps)) if known_gaps else 3000.0
    for index, line in enumerate(lines):
        if isinstance(line["start_ms"], (int, float)):
            line["start_ms"] = int(line["start_ms"])
            line["interpolated"] = False
            continue
        before = next((candidate for candidate in reversed(known) if candidate < index), None)
        after = next((candidate for candidate in known if candidate > index), None)
        if before is not None and after is not None:
            fraction = (index - before) / (after - before)
            value = float(lines[before]["start_ms"]) + fraction * (
                float(lines[after]["start_ms"]) - float(lines[before]["start_ms"])
            )
        elif before is not None:
            value = float(lines[before]["start_ms"]) + fallback_gap * (index - before)
        else:
            value = max(0.0, float(lines[after]["start_ms"]) - fallback_gap * (after - index))
        line["start_ms"] = round(value)
        line["interpolated"] = True
    return lines


def _validate_alignment_document(document: object) -> dict[str, object]:
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise RuntimeError("FA-Kara returned an unsupported alignment document")
    alignment = document.get("alignment")
    if not isinstance(alignment, dict) or not isinstance(alignment.get("lines"), list):
        raise RuntimeError("FA-Kara alignment document has no line records")
    previous_end = 0
    token_count = 0
    for line_index, line in enumerate(alignment["lines"]):
        if not isinstance(line, dict) or line.get("source_index") != line_index:
            raise RuntimeError("FA-Kara alignment document has invalid source indexes")
        tokens = line.get("tokens")
        if not isinstance(tokens, list) or not tokens:
            raise RuntimeError(f"FA-Kara line {line_index} contains no aligned tokens")
        for token in tokens:
            if not isinstance(token, dict):
                raise RuntimeError("FA-Kara alignment document contains an invalid token")
            start = token.get("start_ms")
            end = token.get("end_ms")
            score = token.get("ctc_score")
            if not isinstance(start, int) or not isinstance(end, int) or end < start or start < previous_end:
                raise RuntimeError("FA-Kara alignment document contains non-monotonic timing")
            if not isinstance(score, (int, float)) or not 0 <= float(score) <= 1:
                raise RuntimeError("FA-Kara alignment document contains an invalid CTC score")
            previous_end = end
            token_count += 1
    if token_count == 0:
        raise RuntimeError("FA-Kara alignment document contains no tokens")
    return document


def _fa_kara_worker(vendor: Path, model_revision: str) -> subprocess.Popen[str]:
    global _FA_KARA_WORKER, _FA_KARA_WORKER_KEY
    key = (str(vendor), model_revision)
    if (_FA_KARA_WORKER is not None and _FA_KARA_WORKER.poll() is None
            and _FA_KARA_WORKER_KEY == key):
        return _FA_KARA_WORKER
    if _FA_KARA_WORKER is not None and _FA_KARA_WORKER.poll() is None:
        _FA_KARA_WORKER.terminate()
    numba_cache = Path("/tmp/echora-fa-kara-worker-numba")
    numba_cache.mkdir(parents=True, exist_ok=True)
    environment = {
        **os.environ,
        "NUMBA_CACHE_DIR": str(numba_cache),
        "PYTHONPATH": f"{vendor}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
    }
    _FA_KARA_WORKER = subprocess.Popen(
        [sys.executable, str(vendor / "worker.py")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, bufsize=1, env=environment,
    )
    _FA_KARA_WORKER_KEY = key
    return _FA_KARA_WORKER


def _run_worker_job(worker: subprocess.Popen[str], argv: list[str], timeout: int = 1800) -> dict[str, object]:
    if worker.stdin is None or worker.stdout is None:
        raise RuntimeError("FA-Kara worker pipes are unavailable")
    worker.stdin.write(json.dumps({"argv": argv}, ensure_ascii=False) + "\n")
    worker.stdin.flush()
    selector = selectors.DefaultSelector()
    selector.register(worker.stdout, selectors.EVENT_READ)
    try:
        if not selector.select(timeout):
            worker.kill()
            raise TimeoutError("FA-Kara worker timed out")
        response_line = worker.stdout.readline()
    finally:
        selector.close()
    if not response_line:
        raise RuntimeError(f"FA-Kara worker exited unexpectedly with code {worker.poll()}")
    response = json.loads(response_line)
    if not isinstance(response, dict):
        raise RuntimeError("FA-Kara worker returned an invalid response")
    return response


def _run_fa_kara(audio: bytes, lyrics_text: str, language: str | None,
                 source_lines: list[dict[str, object]] | None = None) -> dict[str, object]:
    vendor = Path(__file__).resolve().parents[2] / "vendor" / "fa_kara"
    model_id = os.environ.get("FA_KARA_MODEL_ID", DEFAULT_MODEL_ID)
    model_revision = os.environ.get("FA_KARA_REVISION", DEFAULT_MODEL_REVISION)
    snapshot = Path(os.environ.get("HF_HOME", "/models/huggingface")) / "hub" / f"models--{model_id.replace('/', '--')}" / "snapshots" / model_revision
    if not snapshot.is_dir():
        raise RuntimeError(f"FA-Kara model snapshot is missing: {model_id}@{model_revision}")
    with tempfile.TemporaryDirectory(prefix="echora-fa-kara-") as directory:
        work = Path(directory)
        audio_path = work / "i.audio"
        audio_path.write_bytes(audio)
        timeline = _anchored_source_lines(source_lines or [])
        input_text = "\n".join(str(line["text"]) for line in timeline) if timeline else lyrics_text.strip()
        (work / "i.txt").write_text(input_text + "\n", encoding="utf-8")
        command = [
            "--path_io", str(work),
            "--input_audio", audio_path.name, "--input_text", "i.txt", "--model", "yohane",
            "--hf_model_path", str(snapshot), "--lang", language if language in {"auto", "ja", "jaen", "zhen", "ko", "ur", "hi", "pa", "indic"} else "auto",
        ]
        if timeline:
            (work / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False), encoding="utf-8")
            command.extend(["--timeline_json", "timeline.json"])
        worker = _fa_kara_worker(vendor, model_revision)
        response = _run_worker_job(worker, command)
        if not response.get("ok"):
            detail = str(response.get("traceback") or response.get("error") or "unknown worker error")
            raise RuntimeError(f"FA-Kara failed: {detail[-4000:]}")
        ass = (work / "o.ass").read_text(encoding="utf-8")
        lrc = (work / "o_ruby.lrc").read_text(encoding="utf-8")
        alignment_document = _validate_alignment_document(
            json.loads((work / "o.alignment.json").read_text(encoding="utf-8"))
        )
        lines = parse_ass_karaoke(ass)
        if not lines:
            raise RuntimeError("FA-Kara produced no aligned lyric lines")
    return {"ass": ass, "lrc": lrc, "lines": lines, "alignment_document": alignment_document,
            "diagnostics": alignment_document.get("diagnostics", {}),
            "model": model_id, "model_revision": model_revision}


def backfill_karaoke(
    url: str,
    username: str,
    password: str,
    progress: Callable[[dict[str, object]], None] | None = None,
    external_ids: list[str] | None = None,
) -> dict[str, int]:
    """Serialize planning and alignment so concurrent sync jobs cannot race."""
    with _KARAOKE_LOCK:
        return _backfill_karaoke(url, username, password, progress, external_ids)


def _backfill_karaoke(
    url: str,
    username: str,
    password: str,
    progress: Callable[[dict[str, object]], None] | None = None,
    external_ids: list[str] | None = None,
) -> dict[str, int]:
    """Align only lyrics documents that arrived with line timestamps."""
    report = progress or (lambda _: None)
    summary = {"total": 0, "aligned": 0, "failed": 0}
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection, NavidromeClient(url, username, password) as client:
        model_revision = f"{FA_KARA_REVISION}:{os.environ.get('FA_KARA_REVISION', DEFAULT_MODEL_REVISION)}"
        planned = plan_karaoke(
            connection, KARAOKE_PIPELINE_REVISION, external_ids, model_revision
        ).karaoke_external_ids
        if not planned:
            report({"phase": "planning", "message": "Karaoke alignment already current",
                    "completed": 0, "total": 0, "unit": "tracks"})
            return summary
        bound_to_source = False
        report({"phase": "models", "message": "Loading FA-Kara alignment model",
                "completed": 0, "total": 1, "unit": "models"})
        with connection.cursor() as cursor:
            cursor.execute(
                f"""SELECT DISTINCT ON (ts.track_id) ts.track_id, ts.external_id, t.title, l.text, l.language, l.provenance->'lines'
                    FROM track_sources ts JOIN tracks t ON t.id=ts.track_id JOIN lyrics l ON l.track_id=ts.track_id
                    WHERE ts.source_type='subsonic' AND ts.external_id=ANY(%s)
                    ORDER BY ts.track_id, ts.id""",
                (list(planned),),
            )
            tracks = cursor.fetchall()
        summary["total"] = len(tracks)
        for index, (track_id, external_id, title, text, language, source_lines) in enumerate(tracks):
            try:
                result = _run_fa_kara(client.audio_bytes(external_id), text, language, source_lines or [])
                result["lines"] = guard_pathological_lead_ins(
                    result["lines"], source_lines or [], result["diagnostics"]
                )
                # Karaoke now always stores the calibrated unbounded path.
                # The targeted lead-in guard handles measured multi-second
                # first-syllable failures without trusting every source window.
                karaoke_provenance = {
                    "alignment_mode": "global_ctc_calibrated_source_prior",
                    "audio_input": "full_mix_with_consecutive_outlier_recovery",
                    "model": result["model"],
                    "pipeline_revision": KARAOKE_PIPELINE_REVISION,
                    "inference_passes": result["diagnostics"].get("inference_passes"),
                    "source_time_prior": {"kind": "robust_affine_calibration_then_huber",
                                          "weight": 0.8, "delta_ms": 750,
                                          "outliers": "disabled"},
                    "source_line_start_stabilization": bound_to_source,
                    "pathological_lead_in_guard": {
                        "minimum_first_syllable_ms": 1200,
                        "minimum_source_delay_ms": 1000,
                    },
                    "vocal_focus_recovery": {
                        "trigger": "consecutive_outliers_or_single_outlier_with_preceding_line",
                        "scope": "contextual_boundary_block_only",
                    },
                    "collapsed_token_fallback": {
                        "trigger": "multiple_sub_120ms_tokens_and_under_half_source_interval",
                        "scope": "trigger_line_and_following_line_separately",
                        "acceptance": "monotonic_and_fewer_collapsed_tokens",
                    },
                    "syllable_duration_source": "predicted_token_end",
                    "bound_to_synced_lines": bound_to_source,
                }
                with connection.cursor() as cursor:
                    cursor.execute(
                        """INSERT INTO karaoke_lyrics_variants
                             (track_id, bounded, lines, ass, lrc, model, model_revision, provenance,
                              alignment_document, diagnostics, created_at)
                           VALUES (%s,%s,%s,%s,%s,'fa_kara',%s,%s,%s,%s,now())
                           ON CONFLICT (track_id, bounded) DO UPDATE SET lines=EXCLUDED.lines,
                             ass=EXCLUDED.ass, lrc=EXCLUDED.lrc, model=EXCLUDED.model,
                             model_revision=EXCLUDED.model_revision, provenance=EXCLUDED.provenance,
                             alignment_document=EXCLUDED.alignment_document,
                             diagnostics=EXCLUDED.diagnostics, created_at=now()""",
                        (track_id, bound_to_source, Jsonb(result["lines"]), result["ass"], result["lrc"],
                         f"{FA_KARA_REVISION}:{result['model_revision']}", Jsonb(karaoke_provenance),
                         Jsonb(result["alignment_document"]), Jsonb(result["diagnostics"])),
                    )
                    cursor.execute(
                        """UPDATE lyrics SET karaoke_lines=%s, karaoke_ass=%s, karaoke_lrc=%s,
                                  karaoke_model='fa_kara', karaoke_model_revision=%s, karaoke_bounded=%s,
                                  karaoke_created_at=now(),
                                  provenance=provenance || %s
                           WHERE track_id=%s""",
                        (Jsonb(result["lines"]), result["ass"], result["lrc"],
                         f"{FA_KARA_REVISION}:{result['model_revision']}", bound_to_source,
                         Jsonb({"karaoke": karaoke_provenance}), track_id),
                    )
                connection.commit()
                summary["aligned"] += 1
            except Exception:
                connection.rollback()
                summary["failed"] += 1
                logger.exception("FA-Kara alignment failed for %s", track_id)
            report({"phase": "karaoke", "message": f"Aligning karaoke lyrics for {title}",
                    "completed": index + 1, "total": len(tracks), "unit": "tracks", "summary": summary})
    return summary
