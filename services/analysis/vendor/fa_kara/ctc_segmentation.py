"""Global CTC forced alignment with soft source-line onset priors.

This module operates only on an already-computed emission lattice. It does not
load an acoustic model, crop audio, or infer line timings independently.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import torch
from torchaudio.functional import TokenSpan


@dataclass(frozen=True)
class SourcePrior:
    target_index: int
    time_seconds: float


def _huber(value: float, delta: float) -> float:
    value = abs(value)
    if value <= delta:
        return 0.5 * value * value / delta
    return value - 0.5 * delta


def align_with_source_priors(
    emission: torch.Tensor,
    token_groups: list[list[int]],
    *,
    blank: int,
    frame_shift_seconds: float,
    source_priors: list[SourcePrior],
    prior_weight: float = 0.8,
    prior_delta_seconds: float = 0.75,
) -> list[list[TokenSpan]]:
    """Align token groups globally using CTC Viterbi and soft onset priors.

    ``emission`` must contain log probabilities with shape ``[frames, labels]``.
    A prior is charged only when the path enters its target token. It therefore
    influences the line onset without pulling every token toward that onset.
    """
    if emission.ndim != 2 or emission.shape[0] == 0:
        raise ValueError("emission must have shape [frames, labels] and contain frames")
    targets = [token for group in token_groups for token in group]
    if not targets:
        raise ValueError("cannot align an empty token sequence")
    if emission.shape[0] < len(targets):
        raise RuntimeError("CTC emission has fewer frames than target tokens")
    if blank < 0 or blank >= emission.shape[1]:
        raise ValueError("blank token is outside the emission vocabulary")
    if any(token < 0 or token >= emission.shape[1] for token in targets):
        raise ValueError("target token is outside the emission vocabulary")

    # Interleave blanks and labels. State 2*i+1 represents target i.
    state_labels = [blank]
    for token in targets:
        state_labels.extend((token, blank))
    labels = torch.tensor(state_labels, dtype=torch.long, device=emission.device)
    state_count = len(state_labels)
    frame_count = int(emission.shape[0])
    negative_inf = torch.tensor(float("-inf"), device=emission.device)

    prior_by_target = {prior.target_index: prior.time_seconds for prior in source_priors}
    scores = torch.full((state_count,), float("-inf"), device=emission.device)
    scores[0] = emission[0, blank]
    if targets:
        initial = emission[0, targets[0]]
        if 0 in prior_by_target:
            initial -= prior_weight * _huber(prior_by_target[0], prior_delta_seconds)
        scores[1] = initial

    # 0 means stay, 1 advance one state, 2 skip a blank. One byte per state.
    backpointers = torch.zeros((frame_count, state_count), dtype=torch.uint8, device="cpu")
    state_indexes = torch.arange(state_count, device=emission.device)
    is_label = state_indexes.remainder(2).eq(1)
    skip_allowed = torch.zeros(state_count, dtype=torch.bool, device=emission.device)
    if state_count > 2:
        skip_allowed[2:] = is_label[2:] & labels[2:].ne(labels[:-2])

    for frame in range(1, frame_count):
        stay = scores
        advance = torch.cat((negative_inf.reshape(1), scores[:-1]))
        skip = torch.cat((negative_inf.repeat(2), scores[:-2]))
        skip = torch.where(skip_allowed, skip, negative_inf)
        choices = torch.stack((stay, advance, skip), dim=0)

        # Priors belong to transitions into the first acoustic token of a line.
        for target_index, expected_time in prior_by_target.items():
            state = target_index * 2 + 1
            if state >= state_count:
                raise ValueError(f"source prior target {target_index} is outside the transcript")
            penalty = prior_weight * _huber(
                frame * frame_shift_seconds - expected_time, prior_delta_seconds
            )
            choices[1:, state] -= penalty

        best_scores, best_moves = choices.max(dim=0)
        scores = best_scores + emission[frame].index_select(0, labels)
        backpointers[frame] = best_moves.to(device="cpu", dtype=torch.uint8)

    final_states = [state_count - 1, state_count - 2]
    state = max(final_states, key=lambda index: float(scores[index]))
    if not math.isfinite(float(scores[state])):
        raise RuntimeError("no finite CTC path exists for the supplied transcript")

    path = [state]
    for frame in range(frame_count - 1, 0, -1):
        move = int(backpointers[frame, state])
        state -= move
        path.append(state)
    path.reverse()

    flat_spans: list[TokenSpan] = []
    for target_index, token in enumerate(targets):
        token_state = target_index * 2 + 1
        frames = [frame for frame, path_state in enumerate(path) if path_state == token_state]
        if not frames:
            raise RuntimeError(f"CTC path omitted target token {target_index}")
        token_scores = emission[frames, token].exp()
        flat_spans.append(TokenSpan(token, frames[0], frames[-1] + 1, float(token_scores.mean())))

    grouped: list[list[TokenSpan]] = []
    offset = 0
    for group in token_groups:
        grouped.append(flat_spans[offset:offset + len(group)])
        offset += len(group)
    return grouped
