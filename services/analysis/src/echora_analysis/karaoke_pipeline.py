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
import uuid

import psycopg
from psycopg.types.json import Jsonb

from .navidrome import NavidromeClient

logger = logging.getLogger(__name__)

FA_KARA_REVISION = "168ca5f01cecaa1290e31c0ce8dc44af8c7451bb"
DEFAULT_MODEL_ID = "NextFire/mms-300m-ForcedAligner-karaoke-ja-Latn"
DEFAULT_MODEL_REVISION = "2ab2b5f46539ee284703c281f286b01d2410ee12"
_DIALOGUE = re.compile(r"^Dialogue: [^,]*,([^,]+),([^,]+),(?:[^,]*,){6}(.*)$")
_KARAOKE_TAG = re.compile(r"\{\\k(\d+)\}")
_ASS_TAG = re.compile(r"\{[^}]*\}")


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


def _run_fa_kara(audio: bytes, lyrics_text: str, language: str | None) -> dict[str, object]:
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
        (work / "i.txt").write_text(lyrics_text.strip() + "\n", encoding="utf-8")
        command = [
            sys.executable, str(vendor / "main.py"), "--path_io", str(work),
            "--input_audio", audio_path.name, "--input_text", "i.txt", "--model", "yohane",
            "--hf_model_path", str(snapshot), "--lang", language if language in {"auto", "ja", "jaen", "zhen"} else "auto",
        ]
        numba_cache = Path(os.environ.get("NUMBA_CACHE_DIR", "/tmp/echora-numba-cache"))
        numba_cache.mkdir(parents=True, exist_ok=True)
        environment = {**os.environ, "NUMBA_CACHE_DIR": str(numba_cache),
                       "PYTHONPATH": f"{vendor}{os.pathsep}{os.environ.get('PYTHONPATH', '')}"}
        completed = subprocess.run(command, capture_output=True, text=True, env=environment, timeout=1800, check=False)
        if completed.returncode:
            detail = (completed.stderr or completed.stdout).strip()[-2000:]
            raise RuntimeError(f"FA-Kara failed: {detail}")
        ass = (work / "o.ass").read_text(encoding="utf-8")
        lrc = (work / "o_ruby.lrc").read_text(encoding="utf-8")
    return {"ass": ass, "lrc": lrc, "lines": parse_ass_karaoke(ass), "model": model_id, "model_revision": model_revision}


def backfill_karaoke(
    url: str,
    username: str,
    password: str,
    progress: Callable[[dict[str, object]], None] | None = None,
    external_ids: list[str] | None = None,
) -> dict[str, int]:
    """Align only lyrics documents that arrived with line timestamps."""
    report = progress or (lambda _: None)
    report({"phase": "models", "message": "Loading FA-Kara alignment model",
            "completed": 4, "total": 4, "unit": "models"})
    summary = {"total": 0, "aligned": 0, "failed": 0}
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection, NavidromeClient(url, username, password) as client:
        clauses = ["ts.source_type='subsonic'", "coalesce((l.provenance->>'synced')::boolean, false)", "l.text IS NOT NULL", "l.karaoke_lines IS NULL"]
        parameters: list[object] = []
        if external_ids is not None:
            clauses.append("ts.external_id=ANY(%s)")
            parameters.append(external_ids)
        with connection.cursor() as cursor:
            cursor.execute(
                f"""SELECT DISTINCT ON (ts.track_id) ts.track_id, ts.external_id, t.title, l.text, l.language
                    FROM track_sources ts JOIN tracks t ON t.id=ts.track_id JOIN lyrics l ON l.track_id=ts.track_id
                    WHERE {' AND '.join(clauses)} ORDER BY ts.track_id, ts.id""",
                parameters,
            )
            tracks = cursor.fetchall()
        summary["total"] = len(tracks)
        for index, (track_id, external_id, title, text, language) in enumerate(tracks):
            try:
                result = _run_fa_kara(client.audio_bytes(external_id), text, language)
                with connection.cursor() as cursor:
                    cursor.execute(
                        """UPDATE lyrics SET karaoke_lines=%s, karaoke_ass=%s, karaoke_lrc=%s,
                                  karaoke_model='fa_kara', karaoke_model_revision=%s, karaoke_created_at=now(),
                                  provenance=provenance || %s
                           WHERE track_id=%s""",
                        (Jsonb(result["lines"]), result["ass"], result["lrc"],
                         f"{FA_KARA_REVISION}:{result['model_revision']}",
                         Jsonb({"karaoke": {"audio_input": "full_mix", "model": result["model"]}}), track_id),
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
