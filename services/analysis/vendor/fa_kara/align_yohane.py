import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import cast

import math
import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
import time

import torch
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
        
        # 时间格式化函数
        def format_time(time_sec):
            minutes, remainder = divmod(time_sec, 60)
            seconds, centiseconds = divmod(remainder, 1)
            return f"[{int(minutes):02d}:{int(seconds):02d}:{math.floor(centiseconds * 100):02d}]"

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
                'start': format_time(original_start),
                'end': format_time(original_end),
                'original_start': original_start,
                'original_end': original_end
            })
        
        end_time = time.time()
        print("Alignment inference executed in", round(end_time - start_time, 3), "seconds")
        return results

    except Exception as e:
        print(f"Error during alignment: {e}")
        return []