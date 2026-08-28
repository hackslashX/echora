import numpy as np

from echora_analysis.hum_search import contour_embedding, indexed_windows, match_contour


def _melody(notes: list[float], frames: int = 8) -> tuple[np.ndarray, np.ndarray]:
    pitch = np.repeat(np.asarray(notes, dtype=np.float32), frames)
    return pitch, np.ones(len(pitch), dtype=bool)


def test_match_is_transposition_invariant_and_finds_offset():
    query, query_mask = _melody([60, 62, 64, 67, 64])
    prefix, _ = _melody([70, 68, 66], frames=10)
    matching, _ = _melody([65, 67, 69, 72, 69])
    suffix, _ = _melody([58, 57, 55], frames=10)
    target = np.concatenate([prefix, matching, suffix])
    target_mask = np.ones(len(target), dtype=bool)

    cost, offset = match_contour(query, query_mask, target, target_mask)

    assert cost < 0.35
    assert 2.5 <= offset <= 3.5


def test_contour_embedding_is_transposition_invariant():
    left, mask = _melody([60, 62, 64, 67, 64])
    right, _ = _melody([67, 69, 71, 74, 71])

    assert np.dot(contour_embedding(left, mask), contour_embedding(right, mask)) > 0.999


def test_indexed_windows_cover_multiple_durations():
    pitch, mask = _melody([60, 62, 64, 67] * 10, frames=5)

    windows = indexed_windows(pitch, mask)

    assert {duration for _, duration, _ in windows} == {8.0, 10.0, 12.0}
    assert all(vector.shape == (192,) for _, _, vector in windows)


def test_unrelated_contour_scores_worse():
    query, query_mask = _melody([60, 62, 64, 67, 64])
    related, related_mask = _melody([67, 69, 71, 74, 71])
    unrelated, unrelated_mask = _melody([60, 55, 61, 54, 62])

    related_cost, _ = match_contour(query, query_mask, related, related_mask)
    unrelated_cost, _ = match_contour(query, query_mask, unrelated, unrelated_mask)

    assert related_cost < unrelated_cost
