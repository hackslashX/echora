import sys
from pathlib import Path

import torch

VENDOR = Path(__file__).resolve().parents[1] / "vendor" / "fa_kara"
sys.path.insert(0, str(VENDOR))

from ctc_segmentation import SourcePrior, align_with_source_priors  # noqa: E402
from align_yohane import (  # noqa: E402
    _assign_ctc_blank_holds,
    _calibrate_source_priors,
    _collapsed_token_count,
    _front_loaded_ratio,
    _inference_chunk_starts,
    _is_collapsed_line,
    _maximum_internal_gap,
)


def test_ctc_blank_frames_extend_the_preceding_acoustic_token():
    from torchaudio.functional import TokenSpan

    spans = [
        [TokenSpan(1, 2, 4, 0.8)],
        [TokenSpan(2, 9, 11, 0.7)],
        [TokenSpan(3, 15, 17, 0.9)],
    ]

    result = _assign_ctc_blank_holds(spans, [(0, 2), (2, 3)])

    assert result[0][-1].end == 9
    assert result[1][-1].end == 11
    assert result[2][-1].end == 17
    assert spans[0][-1].end == 4


def _emission(labels, vocabulary=4):
    logits = torch.full((len(labels), vocabulary), -8.0)
    for frame, label in enumerate(labels):
        logits[frame, label] = 8.0
    return torch.log_softmax(logits, dim=-1)


def test_global_ctc_alignment_returns_monotonic_grouped_spans():
    emission = _emission([0, 1, 1, 0, 2, 2, 0])

    spans = align_with_source_priors(
        emission, [[1], [2]], blank=0, frame_shift_seconds=0.02,
        source_priors=[SourcePrior(0, 0.02), SourcePrior(1, 0.08)],
    )

    assert [(span.start, span.end) for group in spans for span in group] == [(1, 3), (4, 6)]


def test_repeated_ctc_labels_require_an_intervening_blank():
    emission = _emission([0, 1, 0, 1, 0])

    spans = align_with_source_priors(
        emission, [[1], [1]], blank=0, frame_shift_seconds=0.02,
        source_priors=[],
    )

    assert spans[0][0].end <= spans[1][0].start


def test_source_prior_disambiguates_repeated_acoustic_occurrences():
    # Two equally plausible occurrences of token 1. The onset prior should pick
    # the later one instead of the first path available to Viterbi.
    emission = _emission([0, 1, 0, 0, 0, 1, 0])

    spans = align_with_source_priors(
        emission, [[1]], blank=0, frame_shift_seconds=0.1,
        source_priors=[SourcePrior(0, 0.5)], prior_weight=4.0,
    )

    assert spans[0][0].start == 5


def test_source_calibration_corrects_global_offset_and_rejects_bad_line():
    priors, diagnostics = _calibrate_source_priors(
        [10.0, 20.0, 30.0, 40.0],
        [10.5, 20.5, 37.0, 40.5],
        [0, 4, 8, 12],
    )

    assert [prior.target_index for prior in priors] == [0, 4, 12]
    assert all(abs(prior.time_seconds - expected) < 0.01 for prior, expected in zip(priors, [10.5, 20.5, 40.5]))
    assert diagnostics["source_offset_ms"] == 500
    assert diagnostics["source_outlier_lines"] == [2]
    assert diagnostics["trusted_source_line_ratio"] == 0.75


def test_collapsed_line_requires_multiple_short_tokens_and_low_interval_occupancy():
    from torchaudio.functional import TokenSpan

    collapsed = [[TokenSpan(1, 10, 11, 0.8)], [TokenSpan(2, 12, 13, 0.8)]]
    healthy = [[TokenSpan(1, 10, 17, 0.8)], [TokenSpan(2, 18, 25, 0.8)]]

    assert _collapsed_token_count(collapsed, 0.02) == 2
    assert _is_collapsed_line(collapsed, 0.02, 0.0, 2.0)
    assert not _is_collapsed_line(healthy, 0.02, 0.0, 2.0)
    assert not _is_collapsed_line(collapsed, 0.02, 0.0, 0.4)


def test_collapsed_line_rejects_well_occupied_source_interval():
    from torchaudio.functional import TokenSpan

    groups = [
        [TokenSpan(1, 0, 1, 0.8)],
        [TokenSpan(2, 1, 2, 0.8)],
        [TokenSpan(3, 2, 40, 0.8)],
    ]

    assert _collapsed_token_count(groups, 0.02) == 2
    assert not _is_collapsed_line(groups, 0.02, 0.0, 1.0)


def test_internal_gap_marks_line_for_focused_retry():
    from torchaudio.functional import TokenSpan

    groups = [
        [TokenSpan(1, 0, 20, 0.8)],
        [TokenSpan(2, 240, 260, 0.8)],
    ]

    assert _maximum_internal_gap(groups, 0.02) == 4.4
    assert _is_collapsed_line(groups, 0.02, 0.0, 6.0)


def test_front_loaded_line_marks_dense_early_highlighting_for_retry():
    from torchaudio.functional import TokenSpan

    groups = [
        [TokenSpan(token, token * 2, token * 2 + 2, 0.8)]
        for token in range(8)
    ]

    assert _front_loaded_ratio(groups, 0.02, 0.0, 4.0) == 1.0
    assert _is_collapsed_line(groups, 0.02, 0.0, 4.0)


def test_front_load_ignores_short_lines_and_even_pacing():
    from torchaudio.functional import TokenSpan

    short = [[TokenSpan(token, token, token + 1, 0.8)] for token in range(4)]
    even = [[TokenSpan(token, token * 25, token * 25 + 10, 0.8)] for token in range(8)]

    assert _front_loaded_ratio(short, 0.02, 0.0, 4.0) == 0.0
    assert _front_loaded_ratio(even, 0.02, 0.0, 4.0) < 0.45


def test_inference_chunks_do_not_create_tiny_tail_passes():
    sample_rate = 16_000
    chunk = 45 * sample_rate
    overlap = 2 * sample_rate
    step = chunk - overlap

    assert _inference_chunk_starts(step * 5 + 1, chunk, overlap) == [0, step, step * 2, step * 3, step * 4]
    assert _inference_chunk_starts(step * 5 + overlap + 1, chunk, overlap)[-1] == step * 5


def test_impossible_alignment_fails_instead_of_returning_partial_output():
    emission = _emission([0, 1])

    try:
        align_with_source_priors(
            emission, [[1], [2], [3]], blank=0, frame_shift_seconds=0.02,
            source_priors=[],
        )
    except RuntimeError as error:
        assert "fewer frames" in str(error)
    else:
        raise AssertionError("expected alignment failure")
