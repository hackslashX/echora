import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import cast

import math
import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
import time

import torch
import torchaudio
from torchaudio.functional import TokenSpan, merge_tokens, resample
from torchaudio.pipelines import MMS_FA
from torchaudio.pipelines._wav2vec2 import aligner
from torchaudio.transforms import Fade
from transformers import Wav2Vec2CTCTokenizer, Wav2Vec2ForCTC, Wav2Vec2Processor

logger = logging.getLogger(__name__)

TokenizerFn = Callable[[list[str]], list[list[int]]]

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
    def __init__(self, model: str) -> None:
        super().__init__()
        self.model_id = model
        self.processor = Wav2Vec2Processor.from_pretrained(model)
        self.model = Wav2Vec2ForCTC.from_pretrained(model)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")  # pyright: ignore[reportPrivateImportUsage]
        self.model.to(self.device)  # pyright: ignore[reportArgumentType]
        blank = self.model.config.pad_token_id
        assert blank is not None
        self.blank = blank

    @property
    def tokenizer(self) -> Wav2Vec2CTCTokenizer:
        return self.processor.tokenizer  # pyright: ignore[reportAttributeAccessIssue]

    def tokenize(self, batch: list[str]):
        return [self.tokenizer.encode(e, add_special_tokens=False) for e in batch]

    def align(self, tokens: list[list[int]], waveform: torch.Tensor, sample_rate: int):
        logger.info(f"Wav2Vec2ForcedAligner: running {self.model_id} on {self.device=}")
        target_sample_rate = self.processor.feature_extractor.sampling_rate  # pyright: ignore[reportAttributeAccessIssue]
        waveform = resample(waveform, sample_rate, target_sample_rate)
        sample_rate = target_sample_rate
        waveform = waveform.mean(0)
        inputs = self.processor(
            audio=waveform.numpy(),
            sampling_rate=sample_rate,  # pyright: ignore[reportCallIssue]
            return_tensors="pt",  # pyright: ignore[reportCallIssue]
        )
        with torch.inference_mode():
            outputs = self.model(**inputs.to(self.device))
            emission = torch.nn.functional.log_softmax(outputs.logits, dim=-1)
        token_spans = _align_token_spans(emission[0], tokens, blank=self.blank)
        return emission, token_spans, sample_rate


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


def align_audio_with_timeline(audio_file_path, token_lines, line_starts_ms, sr=None, speed=1, use_gpu=True, hf_model_id=None):
    """Align sequential lyric blocks with non-overlapping intelligent padding."""
    if isinstance(audio_file_path, str):
        waveform, sample_rate = torchaudio.load(audio_file_path)
    else:
        waveform = torch.tensor(audio_file_path).float().unsqueeze(0)
        sample_rate = sr

    aligner_model = Wav2Vec2ForcedAligner(hf_model_id)
    duration = waveform.shape[1] / sample_rate
    starts = [max(0.0, float(value) / 1000.0) for value in line_starts_ms]
    results = []
    previous_core_end = 0.0
    for line_start, line_end in _block_ranges(len(token_lines)):
        # Keep the following line as disposable context so CTC can locate the
        # real end of the block. Do not include the previous line: repeated
        # words there can attract the next block's first tokens.
        context_start = line_start
        context_end = min(len(token_lines), line_end + 1)
        context_tokens = [token for line in token_lines[context_start:context_end] for token in line if token]
        core_token_count = sum(len(line) for line in token_lines[line_start:line_end])
        padded_start = starts[line_start] - 0.75
        # Reuse at most 750 ms of already-aligned audio. This keeps context for
        # early vocals without feeding the same previous lyric into two blocks.
        predicted_boundary = min(previous_core_end, starts[line_start] + 0.75)
        window_start = max(0.0, padded_start, predicted_boundary)
        if context_end < len(starts):
            window_end = min(duration, starts[context_end] + 0.75)
        else:
            window_end = min(duration, starts[context_end - 1] + 8.0)
        if not context_tokens or core_token_count == 0 or window_end <= window_start:
            raise RuntimeError(f"Invalid anchored alignment window for lyric line {line_start}")

        segment = waveform[:, int(window_start * sample_rate):int(window_end * sample_rate)]
        encoded = aligner_model.tokenize(context_tokens)
        _, local_spans, local_sample_rate = aligner_model.align(encoded, segment, sample_rate)
        local_frame_duration = 320.0 / local_sample_rate * speed
        context_results = [
            _span_result(token, spans, local_frame_duration, window_start)
            for token, spans in zip(context_tokens, local_spans)
        ]
        local_results = context_results[:core_token_count]
        results.extend(local_results)
        valid_ends = [float(item['original_end']) for item in local_results if 'original_end' in item]
        if valid_ends:
            previous_core_end = max(valid_ends)

    # Produce an isolated proposal for every line, then solve a two-state path
    # across its tokens. This can use precise isolated onsets and contextual
    # endings without permitting reversed or overlapping timestamps.
    line_offset = 0
    for index, line_tokens in enumerate(token_lines):
        count = len(line_tokens)
        line_results = results[line_offset:line_offset + count]
        isolated_start = starts[index]
        isolated_end = starts[index + 1] if index + 1 < len(starts) else min(duration, isolated_start + 8.0)
        if isolated_end > isolated_start and count:
            segment = waveform[:, int(isolated_start * sample_rate):int(isolated_end * sample_rate)]
            encoded = aligner_model.tokenize(line_tokens)
            _, isolated_spans, isolated_sample_rate = aligner_model.align(encoded, segment, sample_rate)
            isolated_frame_duration = 320.0 / isolated_sample_rate * speed
            isolated_results = [
                _span_result(token, spans, isolated_frame_duration, isolated_start)
                for token, spans in zip(line_tokens, isolated_spans)
            ]
            if len(isolated_results) == count and all('original_end' in item for item in isolated_results):
                results[line_offset:line_offset + count] = _hybrid_path(
                    line_results, isolated_results, isolated_start, isolated_end
                )
        line_offset += count

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