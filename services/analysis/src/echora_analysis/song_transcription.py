"""Shared Roformer vocals + windowed MOSS fallback, with sequential GPU inference."""
import re
from contextlib import nullcontext
from .transcription_recovery import WindowDecodeError, stalled_segments
from .roformer import SEPARATION_REVISION
from .preprocessing import vocal_waveform

PROMPT = 'Transcribe the audio. For each segment, start with the timestamp and speaker ID ([S01], [S02], [S03], ...), then the spoken text, and end with the segment timestamp.'


def transcription_prompt(language: str | None) -> str:
    if not language:
        return PROMPT
    return f'Transcribe the audio in {language}. Do not translate it. ' + PROMPT[20:]
PATTERN = re.compile(r'\[(\d+(?:\.\d+)?)\]\[(S\d+|MULTI)\]([^\[\]]*)\[(\d+(?:\.\d+)?)\]')
PIPELINE_REVISION = f'roformer-moss-w60-o12-timing-v7:{SEPARATION_REVISION}'


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

    def transcribe(self, audio_bytes, language: str | None = None, check=lambda: None, diagnostic_sink=lambda _: None, vocal_activity=None, progress=lambda _: None):
        import numpy as np
        import torch
        from huggingface_hub import snapshot_download
        from transformers import AutoModelForCausalLM, LogitsProcessorList, StoppingCriteriaList
        from .vendor.moss.processor import MossTranscribeDiarizeProcessor
        from .transcription_guard import SegmentGuard

        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        dtype = torch.bfloat16 if device == 'cuda' else torch.float32
        check()
        snapshot = snapshot_download(self.model_id, revision=self.revision, local_files_only=True)
        processor = MossTranscribeDiarizeProcessor.from_pretrained(
            snapshot, local_files_only=True, trust_remote_code=True)
        sr = int(processor.feature_extractor.sampling_rate)
        # Reads the prepared stem, or completes separation and releases its model
        # before ASR loads. Karaoke reuses the same source/configuration artifact.
        vocals = vocal_waveform(audio_bytes, sample_rate=sr, check=check)
        duration = len(vocals)/sr
        ranges = list(windows(duration))
        model = AutoModelForCausalLM.from_pretrained(snapshot, trust_remote_code=True,
                    local_files_only=True, dtype=dtype, attn_implementation='sdpa').to(device).eval()
        result = []; diagnostics = []; unresolved = []; timing_repairs = []
        timing_worker_used = False
        try:
            messages = [{'role':'user','content':[{'type':'audio','audio':'in-memory'}, {'type':'text','text':transcription_prompt(language)}]}]
            prompt = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            def decode(start, end, token_limit):
                check()
                with torch.inference_mode(), (torch.autocast('cuda', dtype=dtype) if device == 'cuda' else nullcontext()):
                    inputs = processor(text=prompt, audio=[vocals[round(start*sr):round(end*sr)]],
                        audio_kwargs={'device':device}, return_tensors='pt').to(device)
                    plen = inputs['input_ids'].shape[1]
                    guard = SegmentGuard(processor.tokenizer, plen)
                    def stop_stall(input_ids, scores, **kwargs):
                        generated = input_ids.shape[1]-plen
                        if generated % 64 == 0:
                            check()
                        if generated % 16:
                            return False
                        return stalled_segments(processor.tokenizer.decode(input_ids[0,plen:].tolist(), skip_special_tokens=True))
                    output = model.generate(**inputs, max_new_tokens=token_limit, do_sample=False,
                        stopping_criteria=StoppingCriteriaList([stop_stall]),
                        repetition_penalty=1.0, no_repeat_ngram_size=0,
                        logits_processor=LogitsProcessorList([guard]))
                ids = output[0,plen:]
                text = processor.tokenizer.decode(ids, skip_special_tokens=True).strip()
                attempt = {'start':start,'end':end,'tokens':len(ids),'guard_events':guard.events}
                # Release decode tensors before recursive retries.
                del inputs, output, ids
                try:
                    if stalled_segments(text): raise WindowDecodeError('MOSS repeated a segment without advancing timestamps')
                    if attempt['tokens'] >= token_limit: raise WindowDecodeError('MOSS hit token limit')
                    segments = parse_window(text, start, end-start)
                except ValueError as error:
                    attempt['error'] = str(error)
                    diagnostics.append(attempt)
                    diagnostic_sink({**attempt, 'raw_output':text})
                    raise WindowDecodeError(f'{start:.2f}-{end:.2f}s: {error}', tokens=attempt['tokens']) from error
                diagnostics.append(attempt)
                diagnostic_sink({**attempt, 'raw_output':text})
                return segments, attempt['tokens']

            def retry_policy(start, end):
                from .transcription_evidence import retry_evidence
                samples = vocals[round(start*sr):round(end*sr)]
                rms = float(np.sqrt(np.mean(samples.astype(np.float64)**2))) if samples.size else 0
                evidence = retry_evidence(vocal_activity, start, end, duration, float(20*np.log10(max(rms,1e-12))))
                if evidence:
                    diagnostic_sink({'start':start,'end':end,'retry_evidence':evidence})
                return evidence

            def reconcile(start, end, segments):
                nonlocal timing_worker_used
                from .transcription_timing import compressed_timing, apply_aligned_times
                evidence = compressed_timing(segments, start, end)
                if evidence is None:
                    return segments
                record = {'start':start, 'end':end, **evidence}
                if len(timing_repairs) >= 2:
                    diagnostics.append({**record, 'timing_status':'repair_budget_exhausted'})
                    return segments
                timing_repairs.append(record)
                progress(f'Reconciling compressed timestamps at {start:.0f}–{end:.0f}s')
                check()
                # Generation has finished, so ASR and alignment need not share VRAM.
                model.to('cpu')
                if device == 'cuda': torch.cuda.empty_cache()
                import io
                import soundfile as sf
                from .karaoke_pipeline import _run_fa_kara
                buffer = io.BytesIO()
                sf.write(buffer, vocals[round(start*sr):round(end*sr)], sr,
                         format='WAV', subtype='FLOAT')
                timing_worker_used = True
                try:
                    aligned = _run_fa_kara(buffer.getvalue(),
                        '\n'.join(s['text'] for s in segments), None, separate_vocals=False)
                    corrected = apply_aligned_times(segments, aligned['lines'], start, end)
                    if compressed_timing(corrected, start, end) is not None:
                        raise ValueError('Alignment did not resolve timestamp compression')
                except (ValueError, RuntimeError) as error:
                    if 'out of memory' in str(error).lower():
                        raise
                    check()
                    record.update(status='unresolved', error=str(error)[-1000:])
                    return segments
                check()
                record.update(status='repaired', aligner_model=aligned['model'],
                              aligner_revision=aligned['model_revision'])
                return corrected

            from .transcription_budget import decode_song
            decoded, unresolved, budget = decode_song(ranges, decode, retry_policy, check, progress,
                                                      reconcile=reconcile)
            for i,(start,end) in enumerate(ranges):
                segments = decoded[i]
                left = 0 if i == 0 else (ranges[i-1][1]+start)/2
                right = duration if i == len(ranges)-1 else (end+ranges[i+1][0])/2
                result.extend(s for s in segments if left <= (s['start_ms']+s['end_ms'])/2000 < right)
            check()
        finally:
            if timing_worker_used:
                from .karaoke_pipeline import _stop_fa_kara_worker
                _stop_fa_kara_worker()
            model.to('cpu')
            del model
            if device == 'cuda': torch.cuda.empty_cache()
        if not result: raise ValueError('No usable lyrics generated')
        result.sort(key=lambda s:s['start_ms'])
        return {'text':'\n'.join(s['text'] for s in result), 'status':'available',
                'synced':True, 'lines':result, 'ai_generated':True,
                'transcription':{'model':self.model_id,'revision':self.revision,
                    'pipeline_revision':PIPELINE_REVISION,'separator':'mel-band-roformer',
                    'separator_revision':SEPARATION_REVISION,
                    'windows':diagnostics, 'partial':bool(unresolved),
                    'unresolved_windows':unresolved, 'retry_budget':budget,
                    'timing_repairs':timing_repairs,
                    'recovery_policy':'Omit unresolved retry windows, never globally deduplicate repeated lyrics',
                    'speaker_policy':'Sxx/MULTI labels are unverified'}}
