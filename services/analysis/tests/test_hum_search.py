import numpy as np

from echora_analysis.hum_search import (
    CONTOUR_HZ,
    _coarse_match,
    _match_prepared_motifs,
    _motif_windows,
    _prepare_motifs,
    match_contour,
)


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


def _reference_coarse_match(query, query_mask, target, target_mask):
    query_length = len(query)
    stride = max(1, CONTOUR_HZ // 2)
    best = None
    for tempo in (0.75, 0.9, 1.0, 1.1, 1.25, 1.4, 1.5):
        width = max(20, round(query_length * tempo))
        if width > len(target):
            continue
        starts = np.arange(0, len(target) - width + 1, stride)
        offsets = np.rint(np.linspace(0, width - 1, query_length)).astype(int)
        indices = starts[:, None] + offsets[None, :]
        candidates = target[indices]
        candidate_masks = target_mask[indices]
        overlaps = candidate_masks & query_mask[None, :]
        valid = overlaps.sum(axis=1) >= query_mask.sum() * 0.55
        if not valid.any():
            continue
        safe_overlaps = overlaps.copy()
        safe_overlaps[~valid, 0] = True
        q_values = np.where(safe_overlaps, query[None, :], np.nan)
        c_values = np.where(safe_overlaps, candidates, np.nan)
        q_relative = query[None, :] - np.nanmedian(q_values, axis=1)[:, None]
        c_relative = candidates - np.nanmedian(c_values, axis=1)[:, None]
        deltas = np.minimum(np.abs(q_relative - c_relative), 6.0)
        voiced_counts = overlaps.sum(axis=1)
        coarse = np.divide(
            np.where(overlaps, deltas, 0).sum(axis=1), voiced_counts,
            out=np.full(len(starts), np.inf), where=voiced_counts > 0,
        ) + (1 - overlaps.mean(axis=1))
        coarse[~valid] = np.inf
        index = int(np.argmin(coarse))
        if np.isfinite(coarse[index]) and (best is None or coarse[index] < best[0]):
            best = (float(coarse[index]), int(starts[index]), candidates[index], candidate_masks[index])
    return best


def test_compiled_coarse_match_matches_numpy_reference():
    random = np.random.default_rng(20260829)
    for query_length, target_length in ((31, 150), (57, 320), (100, 700)):
        for _ in range(8):
            query = random.uniform(48, 78, query_length).astype(np.float32)
            target = random.uniform(45, 82, target_length).astype(np.float32)
            query_mask = random.random(query_length) > 0.18
            target_mask = random.random(target_length) > 0.22

            expected = _reference_coarse_match(query, query_mask, target, target_mask)
            actual = _coarse_match(query, query_mask, target, target_mask)

            assert expected is not None
            assert actual is not None
            assert actual[1] == expected[1]
            assert np.array_equal(actual[2], expected[2])
            assert np.array_equal(actual[3], expected[3])
            assert np.isclose(actual[0], expected[0], rtol=1e-6, atol=1e-6)


def test_compiled_motif_batch_matches_individual_matcher():
    random = np.random.default_rng(187)
    query = random.uniform(48, 76, 140).astype(np.float32)
    query_mask = random.random(140) > 0.2
    target = random.uniform(45, 80, 600).astype(np.float32)
    target_mask = random.random(600) > 0.25
    windows = _motif_windows(query, query_mask)

    expected = [match_contour(pitch, mask, target, target_mask) for pitch, mask in windows]
    actual = _match_prepared_motifs(_prepare_motifs(windows), target, target_mask)

    assert len(actual) == len(expected)
    for actual_match, expected_match in zip(actual, expected, strict=True):
        assert np.isclose(actual_match[0], expected_match[0], rtol=0, atol=1e-8)
        assert actual_match[1] == expected_match[1]


def test_motif_windows_include_full_query_long_overlaps_and_short_edges():
    query = np.arange(208, dtype=np.float32)
    mask = np.ones(208, dtype=bool)

    windows = _motif_windows(query, mask)
    plans = [(int(window[0]), len(window)) for window, _ in windows]

    assert plans[0] == (0, 208)
    assert [start for start, width in plans if width == 90] == [0, 20, 40, 60, 80, 100]
    assert [start for start, width in plans if width == 50] == [0, 40, 80, 120, 140]


def test_unrelated_contour_scores_worse():
    query, query_mask = _melody([60, 62, 64, 67, 64])
    related, related_mask = _melody([67, 69, 71, 74, 71])
    unrelated, unrelated_mask = _melody([60, 55, 61, 54, 62])

    related_cost, _ = match_contour(query, query_mask, related, related_mask)
    unrelated_cost, _ = match_contour(query, query_mask, unrelated, unrelated_mask)

    assert related_cost < unrelated_cost
