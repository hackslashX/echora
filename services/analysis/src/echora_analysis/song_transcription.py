"""Demucs + windowed MOSS fallback. Sequential inference, no persistent stems."""
import re
import tempfile
from contextlib import nullcontext
from pathlib import Path

PROMPT = 'Transcribe the audio. For each segment, start with the timestamp and speaker ID ([S01], [S02], [S03], ...), then the spoken text, and end with the segment timestamp.'
PATTERN = re.compile(r'\[(\d+(?:\.\d+)?)\]\[(S\d+|MULTI)\]([^\[\]]*)\[(\d+(?:\.\d+)?)\]')
PIPELINE_REVISION = 'demucs-htdemucs-moss-w60-o12-v1'


def windows(duration):
    if duration <= 0:
        raise ValueError('Empty audio')
    start = 0.0
    while True:
        end = min(duration, start + 60)
        yield start, end
        if end >= duration:
            return
        start += 48


def parse_window(text, offset, duration):
    matches = list(PATTERN.finditer(text.strip()))
    if not matches or ''.join(m[0] for m in matches) != text.strip():
        raise ValueError('Incomplete MOSS transcript')
    segments = []
    for m in matches:
        start, end = float(m[1]), float(m[4])
        if not 0 <= start < end <= duration + .01 or not m[3].strip():
            raise ValueError('Invalid MOSS interval')
        segments.append({'start_ms': round((start + offset)*1000),
                         'end_ms': round((min(end, duration) + offset)*1000),
                         'speaker': m[2], 'text': m[3].strip()})
    return segments


class SongTranscriber:
    def __init__(self, model_id, revision):
        self.model_id, self.revision = model_id, revision

    def transcribe(self, audio_bytes, check=lambda: None):
        import numpy as np
        import torch
        import soxr
        from demucs.api import Separator
        from huggingface_hub import snapshot_download
        from transformers import AutoModelForCausalLM, LogitsProcessorList
        from .vendor.moss.processor import MossTranscribeDiarizeProcessor
        from .transcription_guard import SegmentGuard

        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        dtype = torch.bfloat16 if device == 'cuda' else torch.float32
        check()
        # Separation finishes and releases VRAM before loading the ASR model.
        separator = Separator(model='htdemucs', device=device, shifts=0)
        try:
            with tempfile.TemporaryDirectory(prefix='echora-transcribe-') as tmp:
                path = Path(tmp)/'source.audio'
                path.write_bytes(audio_bytes)
                _, stems = separator.separate_audio_file(str(path))
                vocals = stems['vocals'].mean(dim=0).cpu().numpy()
                sample_rate = separator.samplerate
        finally:
            del separator
            if device == 'cuda': torch.cuda.empty_cache()
        del stems, _
        if device == 'cuda': torch.cuda.empty_cache()
        check()
        snapshot = snapshot_download(self.model_id, revision=self.revision, local_files_only=True)
        processor = MossTranscribeDiarizeProcessor.from_pretrained(snapshot, local_files_only=True)
        sr = int(processor.feature_extractor.sampling_rate)
        vocals = soxr.resample(vocals, sample_rate, sr).astype(np.float32)
        duration = len(vocals)/sr
        ranges = list(windows(duration))
        model = AutoModelForCausalLM.from_pretrained(snapshot, trust_remote_code=True,
                    local_files_only=True, dtype=dtype, attn_implementation='sdpa').to(device).eval()
        result = []; diagnostics = []
        try:
            messages = [{'role':'user','content':[{'type':'audio','audio':'in-memory'}, {'type':'text','text':PROMPT}]}]
            prompt = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            for i,(start,end) in enumerate(ranges):
                check()
                with torch.inference_mode(), (torch.autocast('cuda', dtype=dtype) if device == 'cuda' else nullcontext()):
                    inputs = processor(text=prompt, audio=[vocals[round(start*sr):round(end*sr)]],
                        audio_kwargs={'device':device}, return_tensors='pt').to(device)
                    plen = inputs['input_ids'].shape[1]
                    guard = SegmentGuard(processor.tokenizer, plen)
                    output = model.generate(**inputs, max_new_tokens=2048, do_sample=False,
                        repetition_penalty=1.0, no_repeat_ngram_size=0,
                        logits_processor=LogitsProcessorList([guard]))
                ids = output[0,plen:]
                if len(ids) >= 2048: raise ValueError('MOSS hit token limit')
                text = processor.tokenizer.decode(ids, skip_special_tokens=True).strip()
                segments = parse_window(text, start, end-start)
                left = 0 if i == 0 else (ranges[i-1][1]+start)/2
                right = duration if i == len(ranges)-1 else (end+ranges[i+1][0])/2
                result.extend(s for s in segments if left <= (s['start_ms']+s['end_ms'])/2000 < right)
                diagnostics.append({'start':start,'end':end,'tokens':len(ids),'guard_events':guard.events})
                del inputs, output, ids
            check()
        finally:
            model.to('cpu')
            del model
            if device == 'cuda': torch.cuda.empty_cache()
        if not result: raise ValueError('No usable lyrics generated')
        result.sort(key=lambda s:s['start_ms'])
        return {'text':'\n'.join(s['text'] for s in result), 'status':'available',
                'synced':True, 'lines':result, 'ai_generated':True,
                'transcription':{'model':self.model_id,'revision':self.revision,
                    'pipeline_revision':PIPELINE_REVISION,'separator':'htdemucs',
                    'windows':diagnostics,'speaker_policy':'Sxx/MULTI labels are unverified'}}
