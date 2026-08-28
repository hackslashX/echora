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


def _restore_display_text(
    source_text: str, syllables: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Restore punctuation and spacing omitted from acoustic CTC tokens."""
    if not source_text or not syllables:
        return syllables
    positions: list[tuple[int, int]] = []
    cursor = 0
    folded_source = source_text.casefold()
    for syllable in syllables:
        token_text = str(syllable.get("text") or "")
        if not token_text:
            return syllables
        start = source_text.find(token_text, cursor)
        if start < 0:
            start = folded_source.find(token_text.casefold(), cursor)
        if start < 0:
            return syllables
        end = start + len(token_text)
        positions.append((start, end))
        cursor = end
    restored = [dict(syllable) for syllable in syllables]
    for index, syllable in enumerate(restored):
        start = 0 if index == 0 else positions[index][0]
        end = positions[index + 1][0] if index + 1 < len(positions) else len(source_text)
        syllable["text"] = source_text[start:end]
    return restored


def build_lines_from_alignment_document(document: dict[str, object]) -> list[dict[str, object]]:
    """Build karaoke lines from the alignment document's millisecond-precision timing.

    The alignment document stores token onset and offset in integer milliseconds
    derived directly from frame indices, avoiding the centisecond quantization
    inherent in the ASS ``\\k`` tag format (10 ms resolution).  Using it as the
    primary timing source eliminates the systematic rounding error that
    accumulates across dense syllable sequences.
    """
    alignment = document.get("alignment")
    if not isinstance(alignment, dict):
        return []
    canonical_lines = alignment.get("lines")
    if not isinstance(canonical_lines, list):
        return []
    lines: list[dict[str, object]] = []
    for line_record in canonical_lines:
        if not isinstance(line_record, dict):
            continue
        tokens = line_record.get("tokens")
        if not isinstance(tokens, list) or not tokens:
            continue
        syllables: list[dict[str, object]] = []
        for token in tokens:
            if not isinstance(token, dict):
                continue
            text = str(token.get("text") or "")
            start_ms = token.get("start_ms")
            end_ms = token.get("end_ms")
            if not isinstance(start_ms, int) or not isinstance(end_ms, int):
                continue
            if text:
                syllables.append({"start_ms": start_ms, "end_ms": end_ms, "text": text})
        if not syllables:
            continue
        source_text = str(line_record.get("text") or "")
        syllables = _restore_display_text(source_text, syllables)
        text = source_text or "".join(str(s["text"]) for s in syllables)
        line_start = int(line_record.get("start_ms") or syllables[0]["start_ms"])
        line_end = int(line_record.get("end_ms") or syllables[-1]["end_ms"])
        lines.append({"start_ms": line_start, "end_ms": line_end, "text": text, "syllables": syllables})
    return lines


def apply_adaptive_line_padding(lines: list[dict[str, object]]) -> list[dict[str, object]]:
    """Pad line containers only inside silence between aligned syllables."""
    padded = [{**line, "syllables": [dict(item) for item in line.get("syllables") or []]} for line in lines]
    timed: list[tuple[int, int, int, int] | None] = []
    for line in padded:
        syllables = [item for item in line["syllables"]
                     if int(item.get("end_ms", 0)) > int(item.get("start_ms", 0))]
        if not syllables:
            timed.append(None)
            continue
        first = syllables[0]
        last = syllables[-1]
        first_start, first_end = int(first["start_ms"]), int(first["end_ms"])
        last_start, last_end = int(last["start_ms"]), int(last["end_ms"])
        timed.append((first_start, first_end, last_start, last_end))
        line["start_ms"] = max(0, first_start - min(200, max(0, (first_end - first_start) // 4)))
        line["end_ms"] = last_end + min(200, max(0, (last_end - last_start) // 4))

    for index in range(1, len(padded)):
        previous = timed[index - 1]
        current = timed[index]
        if previous is None or current is None:
            continue
        previous_last_start, previous_last_end = previous[2], previous[3]
        current_first_start, current_first_end = current[0], current[1]
        gap = max(0, current_first_start - previous_last_end)
        desired_start_padding = min(200, max(0, (current_first_end - current_first_start) // 4))
        start_padding = min(desired_start_padding, gap)
        remaining_gap = gap - start_padding
        desired_end_padding = min(200, max(0, (previous_last_end - previous_last_start) // 4))
        end_padding = min(desired_end_padding, remaining_gap)
        padded[index]["start_ms"] = current_first_start - start_padding
        padded[index - 1]["end_ms"] = previous_last_end + end_padding
    return padded


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
    source_lines = _timed_source_lines(source)
    offset = float(diagnostics.get("source_offset_ms", 0))
    slope = 1.0 + float(diagnostics.get("source_drift_ms_per_minute", 0)) / 60000.0
    guarded = []
    guarded_indexes = []
    source_index = 0
    for index, line in enumerate(karaoke):
        syllables = [dict(item) for item in line.get("syllables") or []]
        key = _line_key(line.get("text"))
        match_index = next((candidate for candidate in range(source_index, len(source_lines))
                            if _line_key(source_lines[candidate].get("text")) == key), -1)
        if match_index < 0 or not syllables:
            guarded.append(line)
            continue
        source_index = match_index + 1
        source_start = round(float(source_lines[match_index]["start_ms"]) * slope + offset)
        first_start = int(syllables[0]["start_ms"])
        # A source-confirmed multi-second early onset means CTC consumed a
        # pre-vocal blank. Clamp only the pre-source prefix; later syllables
        # retain their acoustic positions instead of shifting the whole line.
        if source_start < first_start + 1000:
            guarded.append(line)
            continue
        previous_end = source_start
        changed = False
        for syllable in syllables:
            start = int(syllable["start_ms"])
            end = int(syllable["end_ms"])
            if start >= source_start and not changed:
                break
            syllable["start_ms"] = max(start, previous_end)
            syllable["end_ms"] = max(end, int(syllable["start_ms"]) + 100)
            previous_end = int(syllable["end_ms"])
            changed = True
        if not changed:
            guarded.append(line)
            continue
        guarded.append({**line, "start_ms": source_start,
                        "end_ms": max(int(line.get("end_ms") or 0), int(syllables[-1]["end_ms"])),
                        "syllables": syllables})
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


def _stop_fa_kara_worker() -> None:
    global _FA_KARA_WORKER, _FA_KARA_WORKER_KEY
    worker = _FA_KARA_WORKER
    _FA_KARA_WORKER = None
    _FA_KARA_WORKER_KEY = None
    if worker is None or worker.poll() is not None:
        return
    worker.terminate()
    try:
        worker.wait(timeout=10)
    except subprocess.TimeoutExpired:
        worker.kill()
        worker.wait(timeout=5)


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
        separate_vocals = os.environ.get("FA_KARA_VOCAL_SEPARATION", "false").lower() == "true"
        timeline = _anchored_source_lines(source_lines or [])
        input_text = "\n".join(str(line["text"]) for line in timeline) if timeline else lyrics_text.strip()
        (work / "i.txt").write_text(input_text + "\n", encoding="utf-8")
        aligner = os.environ.get("FA_KARA_ALIGNER", "yohane").lower()
        if aligner not in {"yohane", "mms"}:
            raise ValueError("FA_KARA_ALIGNER must be 'yohane' or 'mms'")
        command = [
            "--path_io", str(work),
            "--input_audio", str(audio_path), "--input_text", "i.txt", "--model", aligner,
            "--lang", language if language in {"auto", "ja", "jaen", "zhen", "ko", "ur", "hi", "pa", "indic"} else "auto",
        ]
        if aligner == "yohane":
            command.extend(["--hf_model_path", str(snapshot)])
        if separate_vocals:
            command.append("--separate_vocals")
        command.extend(["--head_correct", "0", "--tail_correct", "0"])
        if timeline:
            (work / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False), encoding="utf-8")
            command.extend(["--timeline_json", "timeline.json"])
        if os.environ.get("FA_KARA_REFINE_ALL_LINES", "false").lower() == "true":
            command.append("--refine_all_lines")
        if os.environ.get("FA_KARA_DURATION_AWARE_PRIORS", "false").lower() == "true":
            command.append("--duration_aware_priors")
        audio_speed = float(os.environ.get("FA_KARA_AUDIO_SPEED", "1"))
        if not 0.5 <= audio_speed <= 1.5:
            raise ValueError("FA_KARA_AUDIO_SPEED must be between 0.5 and 1.5")
        if audio_speed != 1.0:
            command.extend(["--audio_speedx", str(audio_speed)])
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
        if separate_vocals:
            alignment_document.setdefault("diagnostics", {})["audio_source"] = "demucs_vocals"
            alignment_document["diagnostics"]["separator"] = "demucs"
            alignment_document["diagnostics"]["separator_model"] = "htdemucs"
        lines = build_lines_from_alignment_document(alignment_document)
        if not lines:
            lines = parse_ass_karaoke(ass)
        lines = apply_adaptive_line_padding(lines)
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
    """Serialize alignment and release its resident model after the phase."""
    with _KARAOKE_LOCK:
        try:
            return _backfill_karaoke(url, username, password, progress, external_ids)
        finally:
            _stop_fa_kara_worker()


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
