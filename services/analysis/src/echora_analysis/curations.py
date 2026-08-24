from __future__ import annotations

import random
import re
import unicodedata

import numpy as np

from .concepts import combine_concept_percentiles, empirical_percentiles, score_concept


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold()
    return re.sub(r"[^a-z0-9]+", " ", folded).strip()


def resolve_references(prompt: str, rows: list[dict[str, object]]) -> list[dict[str, str]]:
    normalized_prompt = f" {_normalize(prompt)} "
    quoted = {_normalize(value) for value in re.findall(r'["“”]([^"“”]+)["“”]', prompt)}
    found: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        for kind, field in (("track", "title"), ("artist", "artist"), ("album", "album")):
            display = str(row.get(field) or "").strip()
            value = _normalize(display)
            if not value:
                continue
            explicit = value in quoted
            mentioned = len(value) >= 4 and f" {value} " in normalized_prompt
            if explicit or mentioned:
                key = (kind, value)
                found[key] = {"kind": kind, "name": display}
    return sorted(found.values(), key=lambda item: (item["kind"], item["name"].casefold()))


def rank_curation(
    rows: list[dict[str, object]], matrix: np.ndarray, positive_prompt: str, negative_prompt: str,
    track_limit: int, refresh_mode: str, existing_track_ids: list[str] | None = None,
    positive_track_ids: list[str] | None = None, negative_track_ids: list[str] | None = None,
    lyrics_matrix: np.ndarray | None = None, lyrics_available: np.ndarray | None = None,
    lyrics_positive_queries: np.ndarray | None = None,
    lyrics_negative_queries: np.ndarray | None = None,
    listen_counts: dict[str, int] | None = None,
    recent_track_ids: set[str] | None = None,
    familiarity_percent: int = 70,
    shuffle_seed: int | None = None,
) -> tuple[list[dict[str, object]], dict[str, list[dict[str, str]]]]:
    positive_references = resolve_references(positive_prompt, rows)
    negative_references = resolve_references(negative_prompt, rows)
    row_by_id = {str(row["id"]): row for row in rows}
    for identifiers, references in (
        (positive_track_ids or [], positive_references), (negative_track_ids or [], negative_references),
    ):
        for identifier in identifiers:
            row = row_by_id.get(str(identifier))
            if row is not None and not any(item["kind"] == "track" and item["name"] == str(row["title"]) for item in references):
                references.append({"kind": "track", "name": str(row["title"])})

    def indices(references: list[dict[str, str]]) -> list[int]:
        matches: list[int] = []
        for index, row in enumerate(rows):
            for reference in references:
                field = "title" if reference["kind"] == "track" else reference["kind"]
                if _normalize(str(row.get(field) or "")) == _normalize(reference["name"]):
                    matches.append(index)
                    break
        return sorted(set(matches))

    positive_indices = sorted(set(indices(positive_references) + [
        index for index, row in enumerate(rows) if str(row["id"]) in set(positive_track_ids or [])
    ]))
    negative_indices = sorted(set(indices(negative_references) + [
        index for index, row in enumerate(rows) if str(row["id"]) in set(negative_track_ids or [])
    ]))
    semantic_raw, percentiles = score_concept(
        matrix,
        [positive_prompt],
        [negative_prompt] if negative_prompt.strip() else [],
        matrix[positive_indices] if positive_indices else None,
        matrix[negative_indices] if negative_indices else None,
    )
    score = semantic_raw
    semantic_percentiles = empirical_percentiles(semantic_raw)
    lyrics_percentiles = np.full(len(rows), 0.5, dtype=np.float32)
    has_lyrics_examples = any(lyrics_available[index] for index in positive_indices) if lyrics_available is not None else False
    if lyrics_matrix is not None and lyrics_available is not None and (lyrics_positive_queries is not None or has_lyrics_examples):
        positive_parts = list(lyrics_positive_queries) if lyrics_positive_queries is not None else []
        positive_parts.extend(lyrics_matrix[index] for index in positive_indices if lyrics_available[index])
        positive_center = np.mean(positive_parts, axis=0)
        positive_center /= max(float(np.linalg.norm(positive_center)), 1e-8)
        normalized_lyrics = lyrics_matrix / np.maximum(np.linalg.norm(lyrics_matrix, axis=1, keepdims=True), 1e-8)
        lyrics_raw = normalized_lyrics @ positive_center
        negative_parts = list(lyrics_negative_queries) if lyrics_negative_queries is not None else []
        negative_parts.extend(lyrics_matrix[index] for index in negative_indices if lyrics_available[index])
        if negative_parts:
            negative_center = np.mean(negative_parts, axis=0)
            negative_center /= max(float(np.linalg.norm(negative_center)), 1e-8)
            lyrics_raw -= normalized_lyrics @ negative_center
        lyrics_percentiles = empirical_percentiles(lyrics_raw, lyrics_available)
        score, percentiles = combine_concept_percentiles(semantic_raw, lyrics_raw, lyrics_available)
    adjusted = score.copy()
    existing = set(existing_track_ids or [])
    if refresh_mode == "stable" and existing:
        for index, row in enumerate(rows):
            if str(row["id"]) in existing:
                adjusted[index] += 0.035

    counts = listen_counts or {}
    recent = recent_track_ids or set()
    maximum_count = max(counts.values(), default=0)
    familiarity_boost = np.zeros(len(rows), dtype=np.float32)
    if maximum_count:
        for index, row in enumerate(rows):
            count = counts.get(str(row["id"]), 0)
            familiarity_boost[index] = np.log1p(count) / np.log1p(maximum_count) * 0.15
    familiar_order = sorted(
        (index for index, row in enumerate(rows) if counts.get(str(row["id"]), 0) > 0),
        key=lambda index: (float(adjusted[index] + familiarity_boost[index]), str(rows[index]["id"])), reverse=True,
    )
    discovery_order = sorted(
        (index for index, row in enumerate(rows) if str(row["id"]) not in recent),
        key=lambda index: (float(adjusted[index]), str(rows[index]["id"])), reverse=True,
    )
    all_order = [int(index) for index in np.argsort(adjusted + familiarity_boost, kind="stable")[::-1]]
    familiar_target = round(track_limit * familiarity_percent / 100) if listen_counts is not None else 0
    discovery_target = track_limit - familiar_target if listen_counts is not None else track_limit
    selected_indices: list[int] = []
    artist_counts: dict[str, int] = {}

    def take(order: list[int], amount: int) -> None:
        for index in order:
            if len(selected_indices) >= amount or index in selected_indices:
                continue
            artist_key = _normalize(str(rows[index].get("artist") or "Unknown artist"))
            if artist_counts.get(artist_key, 0) >= 2:
                continue
            artist_counts[artist_key] = artist_counts.get(artist_key, 0) + 1
            selected_indices.append(index)

    take(familiar_order, familiar_target)
    familiar_selected = len(selected_indices)
    take(discovery_order, familiar_selected + discovery_target)
    take(all_order, track_limit)
    selected: list[dict[str, object]] = []
    for index in selected_indices:
        row = rows[index]
        count = counts.get(str(row["id"]), 0)
        selected.append({
            **row, "score": float(score[index]), "percentile": float(percentiles[index]),
            "retained": str(row["id"]) in existing,
            "evidence": {
                "semantic_percentile": float(semantic_percentiles[index]),
                "lyrics_percentile": float(lyrics_percentiles[index]),
                "lyrics_available": bool(lyrics_available[index]) if lyrics_available is not None else False,
                "listen_count": count, "selection_pool": "familiar" if count else "discovery",
            },
        })
    random.Random(shuffle_seed).shuffle(selected)
    return selected, {"positive": positive_references, "negative": negative_references}
