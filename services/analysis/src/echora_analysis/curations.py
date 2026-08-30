from __future__ import annotations

import random
import re
import unicodedata

import numpy as np

from .concepts import combine_concept_percentiles, empirical_percentiles, score_concept

# Minimum blended percentile for a track to enter the matching pool. Last.fm
# promotion and the discovery pool both draw from inside this pool; anything
# below it only appears when the pool cannot fill the playlist.
MATCH_PERCENTILE = 0.75


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
    sound_prompts: list[list[str]] | None = None, themes_prompts: list[list[str]] | None = None,
    sound_negative_prompts: list[list[str]] | None = None,
    themes_negative_prompts: list[list[str]] | None = None,
    sound_weight: int | None = None,
    voice_matrix: np.ndarray | None = None, voice_available: np.ndarray | None = None,
) -> tuple[list[dict[str, object]], dict[str, list[dict[str, str]]]]:
    """Rank a curation corpus across the sound (semantic) and themes (lyrics) channels.

    When any prompt list is provided the recipe is structured: each sound tag
    scores only the semantic channel and each themes tag only the lyrics
    channel. Tags are scored independently and their percentiles combine with
    a geometric mean, so a track has to satisfy every tag (a soft AND), and
    sound_weight (0-100) sets the semantic share of the blend. When all are
    None the recipe is legacy: the single positive_prompt scores both channels
    at the historical 45/55 split.

    Selection: tracks scoring at or above MATCH_PERCENTILE form the matching
    pool. Listened tracks inside the pool are guaranteed slots (up to the
    familiarity target); remaining slots come from the top-scoring unheard
    tracks in the pool, then from the best remaining scorers anywhere if the
    pool runs dry. If no listened track clears the threshold, Last.fm is
    ignored and the playlist is all discovery regardless of the slider.
    """
    structured = any(value is not None for value in (
        sound_prompts, themes_prompts, sound_negative_prompts, themes_negative_prompts,
    ))
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
    semantic_active = bool(sound_prompts) or bool(positive_indices)
    tag_evidence: dict[str, list[dict[str, object]]] = {str(row["id"]): [] for row in rows}

    def _geomean_percentiles(per_tag: list[np.ndarray]) -> np.ndarray:
        stacked = np.clip(np.stack(per_tag), 1e-4, 1.0)
        return np.exp(np.mean(np.log(stacked), axis=0)).astype(np.float32)

    if structured:
        negative_groups = sound_negative_prompts or []
        semantic_groups = sound_prompts or []

        def _voice_kind(group: list[str]) -> str | None:
            text = " ".join(group).casefold()
            if "instrumental" in text or "without vocal" in text or "no singing" in text:
                return "instrumental"
            vocal = any(word in text for word in ("vocal", "voice", "sing"))
            if not vocal:
                return None
            if "female" in text or "woman" in text:
                return "female"
            if ("male" in text and "female" not in text) or "man " in text or "man singing" in text:
                return "male"
            return None

        def _voice_percentile(kind: str) -> np.ndarray | None:
            if voice_matrix is None or voice_available is None or not voice_available.any():
                return None
            instrumental, female, male = (voice_matrix[:, 0], voice_matrix[:, 1], voice_matrix[:, 2])
            evidence = {"female": female, "male": male, "instrumental": instrumental}[kind]
            return empirical_percentiles(evidence, voice_available)

        def _semantic_percentile(group: list[str], examples: np.ndarray | None = None) -> np.ndarray:
            _, values = score_concept(matrix, group, positive_examples=examples)
            values = np.asarray(values, dtype=np.float32)
            kind = _voice_kind(group)
            voice_percentiles = _voice_percentile(kind) if kind else None
            if voice_percentiles is not None:
                # Direct voice labels use the dedicated classifier. MuQ remains
                # the fallback only for tracks without classifier evidence.
                values = np.where(voice_available, voice_percentiles, values)
            return values

        per_tag_semantic: list[np.ndarray] = [
            _semantic_percentile(
                group,
                matrix[positive_indices] if positive_indices else None,
            )
            for group in semantic_groups
        ]
        if positive_indices and not semantic_groups:
            per_tag_semantic.append(_semantic_percentile([], matrix[positive_indices]))
        semantic_negative_count = len(negative_groups)
        for group in negative_groups:
            per_tag_semantic.append(1.0 - _semantic_percentile(group))
        if negative_indices:
            _, excluded_examples = score_concept(matrix, [], positive_examples=matrix[negative_indices])
            per_tag_semantic.append(1.0 - np.asarray(excluded_examples, dtype=np.float32))
            semantic_negative_count += 1
        if per_tag_semantic:
            semantic_percentiles = _geomean_percentiles(per_tag_semantic)
            score, percentiles = semantic_percentiles, semantic_percentiles
        else:
            semantic_percentiles = np.full(len(rows), 0.5, dtype=np.float32)
            score = percentiles = semantic_percentiles
        lyrics_percentiles = np.full(len(rows), 0.5, dtype=np.float32)
        per_tag_lyrics: list[np.ndarray] = []
        lyrics_negative_count = 0
        if lyrics_matrix is not None and lyrics_available is not None:
            normalized_lyrics = lyrics_matrix / np.maximum(np.linalg.norm(lyrics_matrix, axis=1, keepdims=True), 1e-8)

            def _lyrics_percentile(center: np.ndarray) -> np.ndarray:
                value = np.asarray(center, dtype=np.float32)
                value /= max(float(np.linalg.norm(value)), 1e-8)
                return np.asarray(empirical_percentiles(normalized_lyrics @ value, lyrics_available), dtype=np.float32)

            positive_centers = np.asarray(lyrics_positive_queries) if lyrics_positive_queries is not None else []
            for center in positive_centers:
                per_tag_lyrics.append(_lyrics_percentile(center))
            negative_centers = np.asarray(lyrics_negative_queries) if lyrics_negative_queries is not None else []
            for center in negative_centers:
                per_tag_lyrics.append(1.0 - _lyrics_percentile(center))
                lyrics_negative_count += 1
            if per_tag_lyrics:
                lyrics_percentiles = _geomean_percentiles(per_tag_lyrics)
                semantic_share = (sound_weight / 100.0 if sound_weight is not None else 0.5) if semantic_active else 0.0
                lyrics_share = 1.0 - semantic_share
                score = semantic_share * semantic_percentiles + lyrics_share * lyrics_percentiles
                percentiles = score.astype(np.float32)
        semantic_positive_count = len(per_tag_semantic) - semantic_negative_count
        for tag_index, tag_percentiles in enumerate(per_tag_semantic):
            for index, row in enumerate(rows):
                tag_evidence[str(row["id"])].append({
                    "channel": "semantic", "tag": tag_index + 1,
                    "negative": tag_index >= semantic_positive_count,
                    "percentile": float(tag_percentiles[index]),
                })
        lyrics_positive_count = len(per_tag_lyrics) - lyrics_negative_count
        for tag_index, tag_percentiles in enumerate(per_tag_lyrics):
            for index, row in enumerate(rows):
                tag_evidence[str(row["id"])].append({
                    "channel": "lyrics", "tag": tag_index + 1,
                    "negative": tag_index >= lyrics_positive_count,
                    "percentile": float(tag_percentiles[index]),
                })
    else:
        semantic_positives = [positive_prompt] if positive_prompt.strip() else []
        semantic_negatives = [negative_prompt] if negative_prompt.strip() else []
        semantic_active = bool(semantic_positives) or bool(positive_indices)
        if semantic_active:
            semantic_raw, percentiles = score_concept(
                matrix,
                semantic_positives,
                semantic_negatives,
                matrix[positive_indices] if positive_indices else None,
                matrix[negative_indices] if negative_indices else None,
            )
        else:
            semantic_raw = np.zeros(len(rows), dtype=np.float32)
            percentiles = np.full(len(rows), 0.5, dtype=np.float32)
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
            if semantic_active:
                score, percentiles = combine_concept_percentiles(
                    semantic_raw, lyrics_raw, lyrics_available, 0.45, 0.55,
                )
            else:
                score, percentiles = lyrics_raw, lyrics_percentiles
    adjusted = score.copy()
    existing = set(existing_track_ids or [])
    if refresh_mode == "stable" and existing:
        for index, row in enumerate(rows):
            if str(row["id"]) in existing:
                adjusted[index] += 0.035

    counts = listen_counts or {}
    # Embedding score filters first; Last.fm only promotes within the high scorers.
    matching_order = [int(index) for index in np.argsort(adjusted, kind="stable")[::-1]
                      if float(percentiles[index]) >= MATCH_PERCENTILE]
    familiar_matching = [index for index in matching_order if counts.get(str(rows[index]["id"]), 0) > 0]
    new_order = [index for index in matching_order if index not in set(familiar_matching)]
    # The slider guides how many familiar slots to aim for, but familiar tracks
    # only come from the matching pool. If none of them cleared the threshold,
    # Last.fm is irrelevant and the whole playlist comes from new tracks.
    familiar_target = min(round(track_limit * familiarity_percent / 100), len(familiar_matching)) if listen_counts is not None else 0
    order_all = [int(index) for index in np.argsort(adjusted, kind="stable")[::-1]]
    selected_indices: list[int] = []
    artist_counts: dict[str, int] = {}
    used_recording_groups: set[str] = set()

    def take(order: list[int], amount: int) -> None:
        for index in order:
            if len(selected_indices) >= amount or index in selected_indices:
                continue
            recording_group = str(rows[index].get("recording_group_id") or "")
            if recording_group and recording_group in used_recording_groups:
                continue
            artist_key = _normalize(str(rows[index].get("artist") or "Unknown artist"))
            if artist_counts.get(artist_key, 0) >= 2:
                continue
            artist_counts[artist_key] = artist_counts.get(artist_key, 0) + 1
            if recording_group:
                used_recording_groups.add(recording_group)
            selected_indices.append(index)

    take(familiar_matching, familiar_target)
    familiar_selected = len(selected_indices)
    take(new_order, track_limit)
    # Matching pool exhausted: fill the rest gradually from the top remaining
    # scorers so the playlist is never short when the threshold is strict.
    take(order_all, track_limit)
    selected: list[dict[str, object]] = []
    for index in selected_indices:
        row = rows[index]
        count = counts.get(str(row["id"]), 0)
        familiar = count > 0 and index in selected_indices[:familiar_selected]
        selected.append({
            **row, "score": float(score[index]), "percentile": float(percentiles[index]),
            "retained": str(row["id"]) in existing,
            "evidence": {
                "semantic_percentile": float(semantic_percentiles[index]),
                "lyrics_percentile": float(lyrics_percentiles[index]),
                "lyrics_available": bool(lyrics_available[index]) if lyrics_available is not None else False,
                "listen_count": count, "selection_pool": "familiar" if familiar else "discovery",
                "tag_percentiles": tag_evidence.get(str(row["id"]), []),
            },
        })
    random.Random(shuffle_seed).shuffle(selected)
    return selected, {"positive": positive_references, "negative": negative_references}
