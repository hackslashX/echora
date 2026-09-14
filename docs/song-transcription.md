# AI lyric transcription

The analysis package can recover lyrics with Demucs `htdemucs` and the published Echora MOSS fine-tune. This is an optional fallback, not a replacement for supplied lyrics.

## Configuration

Compose defaults to the published checkpoint:

```dotenv
MOSS_MODEL_ID=hcX02/echora-moss-0.9b-multilingual-lyrics-transcriber
MOSS_REVISION=1cf9dc6d910a6c90c82d8ddc86b83e1533f39f4e
ECHORA_BATCH_SIZE=128
```

Set both MOSS variables explicitly to empty strings to disable transcription. Outside Compose, no model is enabled unless configured.

To select another checkpoint, set the HF repository ID and its immutable 40-character commit revision. Partial configuration fails explicitly. There is no automatic fallback to base MOSS or an experiment-directory checkpoint.

The shared `echora_analysis.download_models` command downloads the configured MOSS snapshot and `htdemucs`. Run it with the same environment and model volumes as the worker, with HF offline mode disabled for provisioning. Inference loads MOSS from local cache only. The HF snapshot must include the fine-tuned model, tokenizer, processor configuration and required custom modeling code. Custom code executes from the reviewed pinned snapshot.

The processor is vendored from the upstream repository with its Apache license. The model weights are not included in the application repository. Review the published weights' license and training-data redistribution permissions before release.

## Processing order

Library import/sync and lyrics backfill retrieve source lyrics first. For tracks without text and not reported instrumental, the pipeline transcribes vocals before lyric embedding and karaoke alignment. Karaoke backfill now runs the lyrics stage first too.

- Decode source audio using the separator's audio loader. Original bytes live in a temporary file; separated vocals remain in memory.
- Separate vocals before loading MOSS so the models do not compete for GPU memory.
- Process 60-second windows with 12-second overlaps through the entire song.
- Apply segment-local lexical repetition protection. Preserve Sxx and MULTI tags without claiming real speaker identities.
- Merge by segment midpoint ownership. No global text deduplication that would erase repeated choruses.
- Retry incomplete formatting, invalid intervals and token-limit outputs as shorter overlapping windows. Stop identical stalled-timestamp loops early.
- After bounded retries, omit unresolved windows and retain usable regions. Store `partial=true` and `unresolved_windows` in transcription provenance rather than claim complete coverage. If no usable lines remain, fail the track.
- Save failed-window raw output in private container-local `/tmp/echora-transcription-*.json` files; paths are logged. These diagnostic files disappear when the container is replaced.
- Store successful text as `source=transcribed`, with millisecond source lines, `synced=true`, `ai_generated=true`, model revision and decoding provenance.

Provider misses do not erase existing lyrics. AI candidates cannot overwrite existing nonempty lyrics. The karaoke stage merges its own provenance and retains the AI flag. The fullscreen player shows a notice in both synced and karaoke views, on desktop and mobile.

The job batch default is 128 tracks, not a GPU inference batch of 128. Inference remains sequential and cancellation is checked between windows and phases. Failed tracks remain eligible for retry. Transcription is disabled when the model configuration is empty.

## Limitations

Window boundary predictions may disagree, and the midpoint merge can miss or duplicate a line. Valid formatting is not proof of lyric accuracy. Partial recovery does not detect every hallucination: MOSS can emit plausible, well-formatted words during instrumentals. Unresolved-window ranges describe failed attempts and may overlap neighboring accepted windows. MULTI semantics are not verified. Vocal separation can introduce artifacts. Instrumentals incorrectly labeled as missing may produce hallucinations. No confidence score or accuracy guarantee is presented to users.

Provision the pinned snapshot through the shared downloader before starting workers with transcription enabled. An end-to-end worker/player smoke test remains required before release; unit and frontend build checks do not replace it.
