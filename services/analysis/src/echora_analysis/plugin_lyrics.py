"""Read-only native lyrics export. No network calls or analysis during playback."""

from __future__ import annotations

import hashlib
import json
import math
import re
from xml.etree import ElementTree as ET

from .navidrome_integration import connect
from .plugin_ranking import library_namespace

TT = "http://www.w3.org/ns/ttml"
TTM = "http://www.w3.org/ns/ttml#metadata"
XML = "http://www.w3.org/XML/1998/namespace"
ET.register_namespace("", TT)
ET.register_namespace("ttm", TTM)


def original_lines(row):
    timed = (row.get("provenance") or {}).get("lines") or []
    if timed and all(
        isinstance(line, dict) and isinstance(line.get("text"), str) for line in timed
    ):
        return [line["text"] for line in timed]
    return (row.get("text") or "").splitlines()


def source_checksum(lines):
    return hashlib.sha256(
        json.dumps(lines, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def timing(value):
    if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
        milliseconds = round(value)
        hours, remainder = divmod(milliseconds, 3600000)
        minutes, remainder = divmod(remainder, 60000)
        seconds, milliseconds = divmod(remainder, 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
    return None


def timed_attributes(line):
    start, end = timing(line.get("start_ms")), timing(line.get("end_ms"))
    attrs = {"begin": start} if start else {}
    if end and (not start or line["end_ms"] >= line["start_ms"]):
        attrs["end"] = end
    return attrs


def export_lines(row):
    source = original_lines(row)
    karaoke = row.get("karaoke_lines") or []
    provenance = (row.get("provenance") or {}).get("lines") or []
    # Preserve karaoke even when its segmentation differs; translations must then
    # be omitted rather than attaching line IDs to unrelated text.
    if karaoke:
        return karaoke, [line.get("text", "") for line in karaoke] == source
    if provenance:
        return provenance, True
    return [{"text": line} for line in source], True


def safe_translations(row, translations, aligned):
    if not aligned:
        return []
    source = original_lines(row)
    checksum = source_checksum(source)
    selected = {}
    for item in translations:
        if item["status"] != "ready" or item["source_checksum"] != checksum:
            continue
        lines = item["lines"]
        if len(lines) != len(source) or any(
            not isinstance(line, dict)
            or line.get("id") != index
            or not isinstance(line.get("text"), str)
            for index, line in enumerate(lines)
        ):
            continue
        # Prefer provider translations over AI when both exist in one language.
        language = item["target_language"]
        if language not in selected or item["provenance"] == "provider":
            selected[language] = item
    return [selected[key] for key in sorted(selected)]


def ttml(row, translations):
    lines, aligned = export_lines(row)
    root = ET.Element(f"{{{TT}}}tt", {f"{{{XML}}}lang": row.get("language") or "und"})
    if translations:
        head = ET.SubElement(root, f"{{{TT}}}head")
        metadata = ET.SubElement(head, f"{{{TT}}}metadata")
        for item in safe_translations(row, translations, aligned):
            track = ET.SubElement(
                metadata, f"{{{TTM}}}translation", {f"{{{XML}}}lang": item["target_language"]}
            )
            for translated in item["lines"]:
                element = ET.SubElement(
                    track, f"{{{TTM}}}text", {"for": f"line-{translated['id']}"}
                )
                element.text = translated["text"]
    div = ET.SubElement(ET.SubElement(root, f"{{{TT}}}body"), f"{{{TT}}}div")
    for index, line in enumerate(lines):
        paragraph = ET.SubElement(
            div, f"{{{TT}}}p", {"key": f"line-{index}", **timed_attributes(line)}
        )
        syllables = line.get("syllables") or []
        # Never replace authoritative text with incomplete predicted tokens.
        if syllables and "".join(str(s.get("text") or "") for s in syllables) == line.get(
            "text", ""
        ):
            for syllable in syllables:
                span = ET.SubElement(paragraph, f"{{{TT}}}span", timed_attributes(syllable))
                span.text = syllable.get("text") or ""
        else:
            paragraph.text = line.get("text") or ""
    return ET.tostring(root, encoding="unicode")


def lrc(lines):
    def stamp(value):
        milliseconds = round(value)
        minutes, remainder = divmod(milliseconds, 60000)
        seconds, milliseconds = divmod(remainder, 1000)
        return f"{minutes:02d}:{seconds:02d}.{milliseconds:03d}"

    result = []
    for line in lines:
        text = line.get("text") or ""
        if timing(line.get("start_ms")):
            text = f"[{stamp(line['start_ms'])}]{text}"
        result.append(text)
    return "\n".join(result)


def lyrics_response(row, translations, profile):
    if not row or not row.get("text") or not profile.serve_lyrics:
        return {"lyrics": []}
    language = row.get("language") or "und"
    # Reject language-tag injection into headers/XML attributes; XML escapes text.
    if not re.fullmatch(r"[a-zA-Z0-9-]{1,35}", language):
        language = "und"
    if profile.lyrics_format == "ttml":
        return {
            "lyrics": [
                {
                    "lang": language,
                    "text": ttml(row, translations if profile.include_translations else []),
                }
            ]
        }
    lines, aligned = export_lines(row)
    result = [{"lang": language, "text": lrc(lines)}]
    if profile.include_translations:
        for item in safe_translations(row, translations, aligned):
            mapped = [
                {**lines[index], "text": translated["text"], "syllables": []}
                for index, translated in enumerate(item["lines"])
            ]
            result.append({"lang": item["target_language"], "text": lrc(mapped)})
    return {"lyrics": result}


def load_lyrics(principal, source_id):
    if not principal["profile"].serve_lyrics:
        return {"lyrics": []}
    with connect() as db:
        row = db.execute(
            """SELECT t.id,l.text,l.language,l.provenance,k.lines AS karaoke_lines
            FROM user_source_memberships visible
            JOIN libraries lib ON lib.id=visible.library_id AND lib.namespace=%s
            JOIN track_sources ts ON ts.library_id=visible.library_id AND ts.external_id=visible.external_id
                AND ts.source_type='subsonic'
            JOIN tracks t ON t.id=ts.track_id
            LEFT JOIN lyrics l ON l.track_id=t.id
            LEFT JOIN karaoke_lyrics_variants k ON k.track_id=t.id AND k.bounded=false
            WHERE visible.user_id=%s AND visible.external_id=%s LIMIT 1""",
            (library_namespace(principal), principal["user_id"], source_id),
        ).fetchone()
        translations = (
            db.execute(
                """SELECT * FROM lyric_translations
            WHERE track_id=%s AND status='ready' ORDER BY target_language,provenance""",
                (row["id"],),
            ).fetchall()
            if row
            else []
        )
    return lyrics_response(row, translations, principal["profile"])
