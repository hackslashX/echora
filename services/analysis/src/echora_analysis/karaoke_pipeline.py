from __future__ import annotations

from collections.abc import Callable
import json
import logging
import os
from pathlib import Path
import re
import subprocess
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
KARAOKE_PIPELINE_REVISION = "anchored-v10"
DEFAULT_MODEL_ID = "NextFire/mms-300m-ForcedAligner-karaoke-ja-Latn"
DEFAULT_MODEL_REVISION = "2ab2b5f46539ee284703c281f286b01d2410ee12"
_DIALOGUE = re.compile(r"^Dialogue: [^,]*,([^,]+),([^,]+),(?:[^,]*,){6}(.*)$")
_KARAOKE_TAG = re.compile(r"\{\\k(\d+)\}")
_ASS_TAG = re.compile(r"\{[^}]*\}")
_KARAOKE_LOCK = threading.Lock()


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
        timeline = _timed_source_lines(source_lines or [])
        input_text = "\n".join(str(line["text"]) for line in timeline) if timeline else lyrics_text.strip()
        (work / "i.txt").write_text(input_text + "\n", encoding="utf-8")
        command = [
            sys.executable, str(vendor / "main.py"), "--path_io", str(work),
            "--input_audio", audio_path.name, "--input_text", "i.txt", "--model", "yohane",
            "--hf_model_path", str(snapshot), "--lang", language if language in {"auto", "ja", "jaen", "zhen"} else "auto",
        ]
        if timeline:
            (work / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False), encoding="utf-8")
            command.extend(["--timeline_json", "timeline.json"])
        # Numba's cache is not safe when several FA-Kara subprocesses write the
        # same entries. Give every invocation its own writable cache directory.
        numba_cache = work / "numba-cache"
        numba_cache.mkdir(parents=True, exist_ok=True)
        environment = {**os.environ, "NUMBA_CACHE_DIR": str(numba_cache),
                       "PYTHONPATH": f"{vendor}{os.pathsep}{os.environ.get('PYTHONPATH', '')}"}
        completed = subprocess.run(command, capture_output=True, text=True, env=environment, timeout=1800, check=False)
        if completed.returncode:
            detail = (completed.stderr or completed.stdout).strip()[-2000:]
            raise RuntimeError(f"FA-Kara failed: {detail}")
        ass = (work / "o.ass").read_text(encoding="utf-8")
        lrc = (work / "o_ruby.lrc").read_text(encoding="utf-8")
        lines = parse_ass_karaoke(ass)
        if not lines:
            raise RuntimeError("FA-Kara produced no aligned lyric lines")
    return {"ass": ass, "lrc": lrc, "lines": lines, "model": model_id, "model_revision": model_revision}


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
        planned = plan_karaoke(connection, KARAOKE_PIPELINE_REVISION, external_ids).karaoke_external_ids
        if not planned:
            report({"phase": "planning", "message": "Karaoke alignment already current",
                    "completed": 0, "total": 0, "unit": "tracks"})
            return summary
        with connection.cursor() as cursor:
            cursor.execute("SELECT karaoke_bound_to_synced_lines FROM analysis_settings WHERE singleton=true")
            setting = cursor.fetchone()
        bound_to_source = bool(setting[0]) if setting else True
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
                result["lines"] = stabilize_to_synced_lines(result["lines"], source_lines or [])
                if bound_to_source:
                    result["lines"] = bound_to_synced_lines(result["lines"], source_lines or [])
                karaoke_provenance = {
                    "alignment_mode": "source_timeline_anchored",
                    "audio_input": "full_mix",
                    "model": result["model"],
                    "pipeline_revision": KARAOKE_PIPELINE_REVISION,
                    "window_padding_ms": {"before": 750, "after": 750, "last_line_after": 8000},
                    "line_block_size": {"minimum": 3, "target": 4, "maximum": 5},
                    "following_context_lines": 1,
                    "clip_start_after_previous_prediction": True,
                    "maximum_boundary_intrusion_ms": 750,
                    "source_line_start_stabilization": True,
                    "syllable_duration_source": "predicted_token_end",
                    "hybrid_alignment": {"proposals": ["contextual_block", "isolated_line"],
                                         "solver": "two_state_monotonic_dynamic_programming",
                                         "switch_penalty": 0.12,
                                         "crop_edge_penalty": 0.8},
                    "bound_to_synced_lines": bound_to_source,
                }
                with connection.cursor() as cursor:
                    cursor.execute(
                        """INSERT INTO karaoke_lyrics_variants
                             (track_id, bounded, lines, ass, lrc, model, model_revision, provenance, created_at)
                           VALUES (%s,%s,%s,%s,%s,'fa_kara',%s,%s,now())
                           ON CONFLICT (track_id, bounded) DO UPDATE SET lines=EXCLUDED.lines,
                             ass=EXCLUDED.ass, lrc=EXCLUDED.lrc, model=EXCLUDED.model,
                             model_revision=EXCLUDED.model_revision, provenance=EXCLUDED.provenance,
                             created_at=now()""",
                        (track_id, bound_to_source, Jsonb(result["lines"]), result["ass"], result["lrc"],
                         f"{FA_KARA_REVISION}:{result['model_revision']}", Jsonb(karaoke_provenance)),
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
