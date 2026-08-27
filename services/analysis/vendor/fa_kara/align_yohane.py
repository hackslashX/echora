import logging
from abc import ABC, abstractmethod
import statistics
from collections.abc import Callable
from typing import cast

import math
import time

import torch
import torchaudio
from torchaudio.functional import (
    TokenSpan, equalizer_biquad, highpass_biquad, lowpass_biquad,
    merge_tokens, resample,
)
from torchaudio.pipelines import MMS_FA
from torchaudio.pipelines._wav2vec2 import aligner
from torchaudio.transforms import Fade
from transformers import Wav2Vec2CTCTokenizer, Wav2Vec2ForCTC, Wav2Vec2Processor

from ctc_segmentation import SourcePrior, align_with_source_priors

logger = logging.getLogger(__name__)

TokenizerFn = Callable[[list[str]], list[list[int]]]
_WAV2VEC_ALIGNER_CACHE: dict[tuple[str, bool], "Wav2Vec2ForcedAligner"] = {}

class ForcedAligner(ABC):
    @abstractmethod
    def tokenize(
        self,
        batch: list[str],
    ) -> list[list[int]]: ...

    @abstractmethod
    def align(
        self,
        tokens: list[list[int]],
        waveform: torch.Tensor,
        sample_rate: int,
    ) -> tuple[torch.Tensor, list[list[TokenSpan]], int]: ...


class TorchAudioForcedAligner(ForcedAligner):
    """
    https://pytorch.org/audio/stable/tutorials/forced_alignment_for_multilingual_data_tutorial.html
    """

    bundle = MMS_FA

    def __init__(self) -> None:
        super().__init__()
        self.tokenizer = self.bundle.get_tokenizer()
        self.model = self.bundle.get_model()
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")  # pyright: ignore[reportPrivateImportUsage]
        self.model.to(self.device)
        self.aligner = self.bundle.get_aligner()

    def tokenize(self, batch: list[str]):
        return cast(list[list[int]], self.tokenizer(batch))

    def align(self, tokens: list[list[int]], waveform: torch.Tensor, sample_rate: int):
        logger.info(f"TorchAudioForcedAligner: running MMS_FA on {self.device}")
        waveform = resample(waveform, sample_rate, int(self.bundle.sample_rate))
        waveform = waveform.mean(0, keepdim=True)
        with torch.inference_mode():
            emission, _ = self.model(waveform.to(self.device))
            emission = cast(torch.Tensor, emission)
        token_spans = self.aligner(emission[0], tokens)
        return emission, token_spans, int(self.bundle.sample_rate)


class Wav2Vec2ForcedAligner(ForcedAligner):
    def __init__(self, model: str, *, use_gpu: bool = True) -> None:
        super().__init__()
        self.model_id = model
        self.processor = Wav2Vec2Processor.from_pretrained(model)
        self.model = Wav2Vec2ForCTC.from_pretrained(model)
        self.device = torch.device("cuda" if use_gpu and torch.cuda.is_available() else "cpu")
        self.model.to(self.device)  # pyright: ignore[reportArgumentType]
        blank = self.model.config.pad_token_id
        assert blank is not None
        self.blank = blank

    @property
    def tokenizer(self) -> Wav2Vec2CTCTokenizer:
        return self.processor.tokenizer  # pyright: ignore[reportAttributeAccessIssue]

    def tokenize(self, batch: list[str]):
        return [self.tokenizer.encode(e, add_special_tokens=False) for e in batch]

    def infer(self, waveform: torch.Tensor, sample_rate: int) -> tuple[torch.Tensor, int, float]:
        """Compute one stitched full-track lattice from model-safe audio chunks."""
        logger.info("Wav2Vec2ForcedAligner: running %s on %s", self.model_id, self.device)
        target_sample_rate = self.processor.feature_extractor.sampling_rate  # pyright: ignore[reportAttributeAccessIssue]
        waveform = resample(waveform, sample_rate, target_sample_rate).mean(0)
        duration_seconds = waveform.numel() / target_sample_rate
        chunk_samples = 45 * target_sample_rate
        overlap_samples = 2 * target_sample_rate
        step_samples = chunk_samples - overlap_samples
        emissions = []
        starts = list(range(0, waveform.numel(), step_samples))
        for chunk_index, start in enumerate(starts):
            chunk = waveform[start:min(waveform.numel(), start + chunk_samples)]
            inputs = self.processor(
                audio=chunk.numpy(), sampling_rate=target_sample_rate,
                return_tensors="pt",  # pyright: ignore[reportCallIssue]
            )
            with torch.inference_mode():
                outputs = self.model(**inputs.to(self.device))
                local = torch.nn.functional.log_softmax(outputs.logits[0], dim=-1).cpu()
            # Adjacent chunks share two seconds. Keep one half on each side so
            # no frame is decoded twice and edge-context damage is minimized.
            overlap_frames = round(local.shape[0] * overlap_samples / max(1, chunk.numel()))
            trim_left = overlap_frames // 2 if chunk_index else 0
            trim_right = overlap_frames - overlap_frames // 2 if chunk_index + 1 < len(starts) else 0
            emissions.append(local[trim_left:local.shape[0] - trim_right if trim_right else None])
        emission = torch.cat(emissions, dim=0)
        self.last_inference_passes = len(emissions)
        frame_shift_seconds = duration_seconds / emission.shape[0]
        return emission, target_sample_rate, frame_shift_seconds

    def align(self, tokens: list[list[int]], waveform: torch.Tensor, sample_rate: int):
        emission, sample_rate, _ = self.infer(waveform, sample_rate)
        token_spans = _align_token_spans(emission, tokens, blank=self.blank)
        return emission.unsqueeze(0), token_spans, sample_rate


def _align_token_spans(
    emission: torch.Tensor, tokens: list[list[int]], *, blank: int
) -> list[list[TokenSpan]]:
    aligned_tokens, scores = aligner._align_emission_and_tokens(
        emission, _flatten_token_sequences(tokens), blank=blank
    )
    spans = merge_tokens(aligned_tokens, scores, blank=blank)
    return _unflatten_token_spans(spans, [len(seq) for seq in tokens])


def _flatten_token_sequences(tokens: list[list[int]]) -> list[int]:
    return [token for seq in tokens for token in seq]


def _unflatten_token_spans(
    spans: list[TokenSpan], token_lengths: list[int]
) -> list[list[TokenSpan]]:
    if len(spans) != sum(token_lengths):
        raise RuntimeError(
            "Forced alignment returned a different number of token spans than tokens."
        )
    offset = 0
    grouped_spans: list[list[TokenSpan]] = []
    for length in token_lengths:
        grouped_spans.append(spans[offset : offset + length])
        offset += length
    return grouped_spans


def _format_time(time_sec):
    minutes, remainder = divmod(max(0.0, time_sec), 60)
    seconds, centiseconds = divmod(remainder, 1)
    return f"[{int(minutes):02d}:{int(seconds):02d}:{math.floor(centiseconds * 100):02d}]"


def _block_ranges(line_count):
    """Partition lines into contextual blocks of three to five."""
    ranges = []
    start = 0
    while start < line_count:
        remaining = line_count - start
        if remaining <= 5:
            size = remaining
        else:
            size = 4
            if remaining - size < 3:
                size = remaining - 3
        ranges.append((start, start + size))
        start += size
    return ranges


def _span_result(token, spans, frame_duration, offset=0.0):
    if not spans:
        return {'token': token, 'start': '[error]', 'end': '[error]', 'score': 0.0}
    start = offset + spans[0].start * frame_duration
    end = offset + spans[-1].end * frame_duration
    score = sum(float(span.score) for span in spans) / len(spans)
    return {
        'token': token, 'start': _format_time(start), 'end': _format_time(end),
        'original_start': start, 'original_end': end, 'score': score,
    }


def _candidate_cost(item, line_start, line_end, final_token, isolated):
    start = float(item.get('original_start', line_start))
    end = float(item.get('original_end', start))
    duration = max(0.0, end - start)
    score = max(0.001, float(item.get('score', 0.001)))
    cost = -math.log(score) * 0.35
    if duration < 0.04:
        cost += 0.4
    hold_limit = 2.5 if final_token else 1.2
    if duration > hold_limit:
        cost += (duration - hold_limit) * 1.5
    if start < line_start - 0.25:
        cost += (line_start - 0.25 - start) * 2.0
    if end > line_end + 0.25:
        cost += (end - line_end - 0.25) * 2.0
    if isolated and end >= line_end - 0.08:
        cost += 0.8
    return cost


def _hybrid_path(contextual, isolated, line_start, line_end):
    """Choose contextual or isolated timing per token with a monotonic DP."""
    if len(contextual) != len(isolated) or not contextual:
        return contextual
    candidates = [[contextual[index], isolated[index]] for index in range(len(contextual))]
    costs = [[float('inf'), float('inf')] for _ in candidates]
    previous = [[None, None] for _ in candidates]
    for state in range(2):
        costs[0][state] = _candidate_cost(
            candidates[0][state], line_start, line_end, len(candidates) == 1, state == 1
        )
    for index in range(1, len(candidates)):
        for state in range(2):
            current = candidates[index][state]
            current_start = float(current.get('original_start', 0))
            unary = _candidate_cost(
                current, line_start, line_end, index == len(candidates) - 1, state == 1
            )
            for prior_state in range(2):
                prior = candidates[index - 1][prior_state]
                prior_end = float(prior.get('original_end', 0))
                if current_start < prior_end - 0.02:
                    continue
                gap = max(0.0, current_start - prior_end)
                transition = max(0.0, gap - 1.0) * 0.4
                if state != prior_state:
                    transition += 0.12
                total = costs[index - 1][prior_state] + unary + transition
                if total < costs[index][state]:
                    costs[index][state] = total
                    previous[index][state] = prior_state
    state = min(range(2), key=lambda value: costs[-1][value])
    if math.isinf(costs[-1][state]):
        return contextual
    states = [state]
    for index in range(len(candidates) - 1, 0, -1):
        state = previous[index][state]
        if state is None:
            return contextual
        states.append(state)
    states.reverse()
    return [candidates[index][state] for index, state in enumerate(states)]


def _vocal_focus_waveform(waveform: torch.Tensor, sample_rate: int) -> torch.Tensor:
    focused = highpass_biquad(waveform.clone(), sample_rate, 100.0)
    focused = equalizer_biquad(focused, sample_rate, 250.0, -3.0, Q=0.8)
    focused = equalizer_biquad(focused, sample_rate, 2200.0, 4.0, Q=0.7)
    focused = equalizer_biquad(focused, sample_rate, 4200.0, 2.0, Q=1.0)
    focused = lowpass_biquad(focused, sample_rate, min(9500.0, sample_rate * 0.45))
    rms = focused.square().mean().sqrt().clamp_min(1e-6)
    return torch.tanh(focused * (0.12 / rms) * 1.8) / 1.8


def _line_span_score(groups: list[list[TokenSpan]]) -> float:
    scores = [float(span.score) for group in groups for span in group]
    return statistics.fmean(scores) if scores else 0.0


def _collapsed_token_count(groups: list[list[TokenSpan]], frame_shift: float,
                           threshold_seconds: float = 0.12) -> int:
    """Count acoustic tokens whose complete CTC span is implausibly short."""
    return sum(
        1 for group in groups
        if group and (group[-1].end - group[0].start) * frame_shift < threshold_seconds
    )


def _is_collapsed_line(groups: list[list[TokenSpan]], frame_shift: float,
                       interval_start: float, interval_end: float) -> bool:
    """Identify strict fallback candidates without disturbing normal global CTC."""
    if _collapsed_token_count(groups, frame_shift) < 2 or not groups:
        return False
    interval_duration = interval_end - interval_start
    if interval_duration < 0.5:
        return False
    occupied = (groups[-1][-1].end - groups[0][0].start) * frame_shift
    return occupied < interval_duration * 0.5


def _calibrate_source_priors(source_starts, observed_starts, target_indexes):
    """Fit source timestamps to acoustic anchors and reject local outliers."""
    if not (len(source_starts) == len(observed_starts) == len(target_indexes)):
        raise ValueError("source calibration inputs must have equal lengths")
    if not source_starts:
        return [], {"trusted_source_line_ratio": 0.0, "source_outlier_lines": []}
    slopes = []
    for left in range(len(source_starts)):
        for right in range(left + 1, len(source_starts)):
            source_delta = source_starts[right] - source_starts[left]
            if source_delta >= 5.0:
                slopes.append((observed_starts[right] - observed_starts[left]) / source_delta)
    slope = statistics.median(slopes) if slopes else 1.0
    # Gross slope estimates indicate bad acoustic anchors, not real playback
    # speed differences. Keep drift correction deliberately conservative.
    slope = min(1.02, max(0.98, slope))
    offset = statistics.median(
        observed - slope * source
        for source, observed in zip(source_starts, observed_starts)
    )
    signed_residuals = [
        observed - (slope * source + offset)
        for source, observed in zip(source_starts, observed_starts)
    ]
    median_residual = statistics.median(signed_residuals)
    mad = statistics.median(abs(value - median_residual) for value in signed_residuals)
    threshold = min(3.0, max(0.75, 3.0 * 1.4826 * mad))
    trusted = [abs(value - median_residual) <= threshold for value in signed_residuals]
    priors = [
        SourcePrior(target, max(0.0, slope * source + offset))
        for source, target, keep in zip(source_starts, target_indexes, trusted) if keep
    ]
    outliers = [index for index, keep in enumerate(trusted) if not keep]
    diagnostics = {
        "source_offset_ms": round(offset * 1000),
        "source_drift_ms_per_minute": round((slope - 1.0) * 60000),
        "median_source_residual_ms": round(statistics.median(abs(value) for value in signed_residuals) * 1000),
        "source_outlier_lines": outliers,
        "trusted_source_line_ratio": sum(trusted) / len(trusted),
        "source_prior_residual_threshold_ms": round(threshold * 1000),
    }
    return priors, diagnostics


def _wav2vec_aligner(model: str, use_gpu: bool) -> Wav2Vec2ForcedAligner:
    key = (model, bool(use_gpu))
    cached = _WAV2VEC_ALIGNER_CACHE.get(key)
    if cached is None:
        cached = Wav2Vec2ForcedAligner(model, use_gpu=use_gpu)
        _WAV2VEC_ALIGNER_CACHE[key] = cached
    return cached


def align_audio_with_timeline(audio_file_path, token_lines, line_starts_ms, sr=None, speed=1, use_gpu=True, hf_model_id=None):
    """Align the complete song from one emission lattice with soft line priors."""
    if isinstance(audio_file_path, str):
        waveform, sample_rate = torchaudio.load(audio_file_path)
    else:
        waveform = torch.tensor(audio_file_path).float().unsqueeze(0)
        sample_rate = sr
    if sample_rate is None:
        raise ValueError("sample rate is required")
    if len(token_lines) != len(line_starts_ms) or not token_lines:
        raise ValueError("token lines and source timestamps must be non-empty and equal in length")

    acoustic_tokens = [token for line in token_lines for token in line if token]
    if not acoustic_tokens:
        raise ValueError("lyrics contain no alignable acoustic tokens")
    aligner_model = _wav2vec_aligner(hf_model_id, use_gpu)
    encoded = aligner_model.tokenize(acoustic_tokens)
    if len(encoded) != len(acoustic_tokens) or any(not group for group in encoded):
        raise RuntimeError("tokenizer omitted one or more acoustic tokens")

    emission, _, frame_shift = aligner_model.infer(waveform, sample_rate)
    original_inference_passes = aligner_model.last_inference_passes
    line_target_indexes = []
    line_acoustic_indexes = []
    line_acoustic_ranges = []
    acoustic_offset = 0
    target_offset = 0
    for line in token_lines:
        line_token_count = sum(1 for token in line if token)
        if line_token_count:
            line_target_indexes.append(target_offset)
            line_acoustic_indexes.append(acoustic_offset)
            line_acoustic_ranges.append((acoustic_offset, acoustic_offset + line_token_count))
            target_offset += sum(len(group) for group in encoded[acoustic_offset:acoustic_offset + line_token_count])
            acoustic_offset += line_token_count

    # First pass is acoustic-only. It lets us estimate whether the supplied
    # source timeline has a global offset, drift, or isolated bad lines.
    initial_spans = align_with_source_priors(
        emission, encoded, blank=aligner_model.blank,
        frame_shift_seconds=frame_shift, source_priors=[],
    )
    observed_starts = [initial_spans[index][0].start * frame_shift for index in line_acoustic_indexes]
    source_starts = [max(0.0, float(value) / 1000.0) for value in line_starts_ms]
    priors, source_diagnostics = _calibrate_source_priors(
        source_starts, observed_starts, line_target_indexes
    )
    spans = align_with_source_priors(
        emission, encoded, blank=aligner_model.blank,
        frame_shift_seconds=frame_shift, source_priors=priors,
    )

    # Recover only consecutive outlier blocks. Isolated lines stay on the
    # global path, avoiding the aggressive per-line replacement experiments.
    outlier_lines = sorted(set(source_diagnostics.get("source_outlier_lines", [])))
    runs = []
    for line_index in outlier_lines:
        if runs and line_index == runs[-1][-1] + 1:
            runs[-1].append(line_index)
        else:
            runs.append([line_index])
    recovery_runs = []
    for run in runs:
        if len(run) >= 2:
            recovery_runs.append(run)
        elif run[0] > 0:
            # A single bad line often means the boundary from its preceding
            # line was consumed too early. Retry both sides of that boundary.
            recovery_runs.append([run[0] - 1, run[0]])
        else:
            # A long instrumental intro can attract the first lyric line. It
            # has no preceding context, so retry it alone near its source cue.
            recovery_runs.append([0])
    recovered_lines = []
    recovery_candidates = []
    recovery_passes = 0
    if recovery_runs:
        focused_waveform = _vocal_focus_waveform(waveform, sample_rate)
        offset = float(source_diagnostics.get("source_offset_ms", 0)) / 1000.0
        slope = 1.0 + float(source_diagnostics.get("source_drift_ms_per_minute", 0)) / 60000.0
        duration = waveform.shape[1] / sample_rate
        for run in recovery_runs:
            first_line, last_line = run[0], run[-1]
            acoustic_start = line_acoustic_ranges[first_line][0]
            acoustic_end = line_acoustic_ranges[last_line][1]
            expanded_singleton = first_line not in outlier_lines and last_line in outlier_lines
            margin_before = 0.75 if expanded_singleton else 1.5
            margin_after = 0.25 if expanded_singleton else 1.5
            window_start = max(0.0, slope * source_starts[first_line] + offset - margin_before)
            if last_line + 1 < len(source_starts):
                window_end = min(duration, slope * source_starts[last_line + 1] + offset + margin_after)
            else:
                window_end = min(duration, slope * source_starts[last_line] + offset + 8.0)
            if window_end <= window_start:
                continue
            segment = focused_waveform[:, int(window_start * sample_rate):int(window_end * sample_rate)]
            local_emission, _, local_shift = aligner_model.infer(segment, sample_rate)
            recovery_passes += aligner_model.last_inference_passes
            local_encoded = encoded[acoustic_start:acoustic_end]
            local_priors = []
            local_target = 0
            for line_index in run:
                local_priors.append(SourcePrior(
                    local_target,
                    max(0.0, slope * source_starts[line_index] + offset - window_start),
                ))
                start, end = line_acoustic_ranges[line_index]
                local_target += sum(len(group) for group in encoded[start:end])
            local_spans = align_with_source_priors(
                local_emission, local_encoded, blank=aligner_model.blank,
                frame_shift_seconds=local_shift, source_priors=local_priors,
                prior_weight=3.0 if expanded_singleton else 1.2,
            )
            local_start = window_start + local_spans[0][0].start * local_shift
            local_end = window_start + local_spans[-1][-1].end * local_shift
            previous_end = spans[acoustic_start - 1][-1].end * frame_shift if acoustic_start else 0.0
            next_start = spans[acoustic_end][0].start * frame_shift if acoustic_end < len(spans) else float("inf")
            local_score = _line_span_score(local_spans)
            original_score = _line_span_score(spans[acoustic_start:acoustic_end])
            candidate = {
                "lines": run, "start_ms": round(local_start * 1000),
                "end_ms": round(local_end * 1000), "previous_end_ms": round(previous_end * 1000),
                "next_start_ms": None if not math.isfinite(next_start) else round(next_start * 1000),
                "focused_score": local_score, "original_score": original_score,
            }
            boundary_intrusion = max(0.0, local_end - next_start)
            maximum_intrusion = 1.25 if run == [0] else 0.35
            if local_start < previous_end or boundary_intrusion > maximum_intrusion:
                candidate["rejected"] = "adjacent_line_overlap"
                recovery_candidates.append(candidate)
                continue
            minimum_score_ratio = 0.6 if expanded_singleton else 0.7
            if local_score < original_score * minimum_score_ratio:
                candidate["rejected"] = "lower_ctc_score"
                recovery_candidates.append(candidate)
                continue
            candidate["accepted"] = True
            recovery_candidates.append(candidate)
            boundary_frame = round(next_start / frame_shift) if math.isfinite(next_start) else None
            converted = []
            for group in local_spans:
                converted_group = []
                for span in group:
                    start_frame = round((window_start + span.start * local_shift) / frame_shift)
                    end_frame = round((window_start + span.end * local_shift) / frame_shift)
                    if boundary_frame is not None:
                        start_frame = min(start_frame, boundary_frame)
                        end_frame = min(max(start_frame, end_frame), boundary_frame)
                    converted_group.append(TokenSpan(span.token, start_frame, end_frame, span.score))
                converted.append(converted_group)
            candidate["boundary_intrusion_ms"] = round(boundary_intrusion * 1000)
            spans[acoustic_start:acoustic_end] = converted
            recovered_lines.extend(run)
        source_diagnostics["vocal_focus_attempted_runs"] = recovery_runs
        source_diagnostics["vocal_focus_candidates"] = recovery_candidates
        source_diagnostics["vocal_focus_recovered_lines"] = recovered_lines
        source_diagnostics["vocal_focus_inference_passes"] = recovery_passes

    # Strict collapsed-token fallback. Global CTC (including Twilight's
    # consecutive-block recovery above) remains authoritative unless a line
    # has multiple sub-40ms tokens while using under half of its corrected
    # source interval. Retry that line and its follower independently, never
    # as a combined block, and replace only when collapse count decreases.
    offset = float(source_diagnostics.get("source_offset_ms", 0)) / 1000.0
    slope = 1.0 + float(source_diagnostics.get("source_drift_ms_per_minute", 0)) / 60000.0
    duration = waveform.shape[1] / sample_rate
    corrected_starts = [min(duration, max(0.0, slope * start + offset)) for start in source_starts]
    corrected_ends = corrected_starts[1:] + [duration]
    collapsed_lines = []
    for line_index, (start, end) in enumerate(line_acoustic_ranges):
        if _is_collapsed_line(spans[start:end], frame_shift,
                              corrected_starts[line_index], corrected_ends[line_index]):
            collapsed_lines.append(line_index)
    retry_lines = sorted({candidate for line in collapsed_lines
                          for candidate in (line, line + 1)
                          if candidate < len(line_acoustic_ranges)})
    collapsed_candidates = []
    if retry_lines:
        focused_waveform = _vocal_focus_waveform(waveform, sample_rate)
        for line_index in retry_lines:
            acoustic_start, acoustic_end = line_acoustic_ranges[line_index]
            window_start, window_end = corrected_starts[line_index], corrected_ends[line_index]
            candidate = {"line": line_index, "source_start_ms": round(window_start * 1000),
                         "source_end_ms": round(window_end * 1000)}
            if window_end <= window_start:
                candidate["rejected"] = "empty_corrected_source_interval"
                collapsed_candidates.append(candidate)
                continue
            segment = focused_waveform[:, int(window_start * sample_rate):int(window_end * sample_rate)]
            local_emission, _, local_shift = aligner_model.infer(segment, sample_rate)
            recovery_passes += aligner_model.last_inference_passes
            local_spans = align_with_source_priors(
                local_emission, encoded[acoustic_start:acoustic_end], blank=aligner_model.blank,
                frame_shift_seconds=local_shift, source_priors=[],
            )
            old_count = _collapsed_token_count(spans[acoustic_start:acoustic_end], frame_shift)
            new_count = _collapsed_token_count(local_spans, local_shift)
            local_start = window_start + local_spans[0][0].start * local_shift
            local_end = window_start + local_spans[-1][-1].end * local_shift
            previous_end = spans[acoustic_start - 1][-1].end * frame_shift if acoustic_start else 0.0
            next_start = spans[acoustic_end][0].start * frame_shift if acoustic_end < len(spans) else duration
            candidate.update({"collapsed_tokens_before": old_count, "collapsed_tokens_after": new_count,
                              "start_ms": round(local_start * 1000), "end_ms": round(local_end * 1000)})
            if local_start < previous_end or local_end > next_start:
                candidate["rejected"] = "non_monotonic"
            elif new_count >= old_count:
                candidate["rejected"] = "collapsed_token_count_not_reduced"
            else:
                candidate["accepted"] = True
                spans[acoustic_start:acoustic_end] = [[TokenSpan(
                    span.token,
                    round((window_start + span.start * local_shift) / frame_shift),
                    round((window_start + span.end * local_shift) / frame_shift), span.score,
                ) for span in group] for group in local_spans]
            collapsed_candidates.append(candidate)
        source_diagnostics["collapsed_fallback_trigger_lines"] = collapsed_lines
        source_diagnostics["collapsed_fallback_retry_lines"] = retry_lines
        source_diagnostics["collapsed_fallback_candidates"] = collapsed_candidates
        source_diagnostics["vocal_focus_inference_passes"] = recovery_passes

    if len(spans) != len(acoustic_tokens):
        raise RuntimeError("global CTC alignment returned the wrong token count")
    results = [
        _span_result(token, token_spans, frame_shift * speed)
        for token, token_spans in zip(acoustic_tokens, spans, strict=True)
    ]
    total_inference_passes = original_inference_passes + recovery_passes
    for result in results:
        result['inference_passes'] = total_inference_passes
        result['source_diagnostics'] = source_diagnostics
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return results


def align_audio_with_text(audio_file_path, text_tokens, non_silent_ranges=[], sr=None, speed=1, use_gpu=True, hf_model_id=None):
    ' Hugging Face 微调模型 '

    start_time = time.time()
    device = torch.device("cuda" if use_gpu and torch.cuda.is_available() else "cpu")
    
    try:
        if isinstance(audio_file_path, str):
            waveform, sample_rate = torchaudio.load(audio_file_path)
        else:
            waveform = torch.tensor(audio_file_path).float()
            waveform = waveform.unsqueeze(0)
            sample_rate = sr
        
        # 处理非静音区域
        if non_silent_ranges:
            # 将时间(秒)转换为样本点
            total_samples = waveform.shape[1]
            sample_ranges = []
            for start_sec, end_sec in non_silent_ranges:
                start_sample = int(start_sec * sample_rate / speed)
                end_sample = min(int(end_sec * sample_rate / speed), total_samples)
                sample_ranges.append((start_sample, end_sample))
            
            # 提取并拼接非静音片段
            segments = []
            for start, end in sample_ranges:
                segments.append(waveform[:, start:end])
            waveform = torch.cat(segments, dim=1)

        # 处理有效token
        valid_tokens = [token for token in text_tokens if token]

        # from yohane-2026.5.0
        torch_aligner = Wav2Vec2ForcedAligner(hf_model_id)
        tokens = torch_aligner.tokenize(valid_tokens)
        _, token_spans, tgt_sample_rate = torch_aligner.align(tokens, waveform, sample_rate)

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        # 时间转换参数
        frame_duration = 1.0 / tgt_sample_rate * 320 * speed
        results = []
        
        # 映射回原始时间
        def map_to_original_time(adjusted_time):
            """将处理后的时间映射回原始音频时间"""
            if not non_silent_ranges:
                return adjusted_time
            
            cumulative_duration = 0.0
            for start_sec, end_sec in non_silent_ranges:
                segment_duration = end_sec - start_sec
                if adjusted_time < cumulative_duration + segment_duration:
                    return start_sec + (adjusted_time - cumulative_duration)
                cumulative_duration += segment_duration
            return non_silent_ranges[-1][1]  # 超出范围返回最后时间
        
        # 处理每个token的时间对齐
        for i, spans in enumerate(token_spans):
            if not spans:
                results.append({
                    'token': valid_tokens[i],
                    'start': '[error]',
                    'end': '[error]'
                })
                continue
                
            # 获取调整后的时间
            adjusted_start = spans[0].start * frame_duration
            adjusted_end = spans[-1].end * frame_duration
            
            # 映射回原始音频时间
            original_start = map_to_original_time(adjusted_start)
            original_end = map_to_original_time(adjusted_end)
            
            results.append({
                'token': valid_tokens[i],
                'start': _format_time(original_start),
                'end': _format_time(original_end),
                'original_start': original_start,
                'original_end': original_end
            })
        
        end_time = time.time()
        print("Alignment inference executed in", round(end_time - start_time, 3), "seconds")
        return results

    except Exception as e:
        print(f"Error during alignment: {e}")
        return []