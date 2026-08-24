from __future__ import annotations

import numpy as np


def normalize_rows(values: np.ndarray) -> np.ndarray:
    matrix = np.asarray(values, dtype=np.float32)
    return matrix / np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-8)


def spherical_targets(start: np.ndarray, end: np.ndarray, length: int) -> np.ndarray:
    first, last = normalize_rows(np.stack([start, end]))
    cosine = float(np.clip(first @ last, -1, 1))
    angle = float(np.arccos(cosine))
    amounts = np.linspace(0, 1, length)
    if angle < 1e-6 or abs(np.sin(angle)) < 1e-6:
        return normalize_rows(np.stack([(1 - amount) * first + amount * last for amount in amounts]))
    sine = np.sin(angle)
    return np.stack([
        np.sin((1 - amount) * angle) / sine * first + np.sin(amount * angle) / sine * last
        for amount in amounts
    ]).astype(np.float32)


def select_journey(
    embeddings: np.ndarray,
    targets: np.ndarray,
    start_index: int,
    end_index: int,
    artists: list[str | None],
    recording_groups: list[str | None],
) -> list[tuple[int, float, float]]:
    matrix = normalize_rows(embeddings)
    selected = [start_index]
    used = {start_index, end_index}
    artist_counts: dict[str, int] = {}
    if artists[start_index]:
        artist_counts[artists[start_index].casefold()] = 1
    used_groups = {recording_groups[start_index]} if recording_groups[start_index] else set()
    previous = start_index
    steps: list[tuple[int, float, float]] = [(start_index, 1.0, 0.0)]
    for position, target in enumerate(targets[1:-1], start=1):
        target_scores = matrix @ target
        previous_scores = matrix @ matrix[previous]
        progress = position / (len(targets) - 1)
        endpoint_axis = matrix @ normalize_rows((matrix[end_index] - matrix[start_index])[None, :])[0]
        candidates = np.argsort(target_scores + 0.12 * previous_scores + 0.04 * progress * endpoint_axis)[::-1]
        choice = None
        for candidate_value in candidates:
            candidate = int(candidate_value)
            if candidate in used:
                continue
            artist = artists[candidate].casefold() if artists[candidate] else None
            if artist and artist_counts.get(artist, 0) >= 2:
                continue
            group = recording_groups[candidate]
            if group and group in used_groups:
                continue
            choice = candidate
            break
        if choice is None:
            continue
        used.add(choice); selected.append(choice)
        artist = artists[choice].casefold() if artists[choice] else None
        if artist:
            artist_counts[artist] = artist_counts.get(artist, 0) + 1
        if recording_groups[choice]:
            used_groups.add(recording_groups[choice])
        steps.append((choice, float(target_scores[choice]), float(matrix[previous] @ matrix[choice])))
        previous = choice
    steps.append((end_index, 1.0, float(matrix[previous] @ matrix[end_index])))
    return steps
