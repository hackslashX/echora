# Lyrics translation implementation status

Decisions confirmed: instance-wide admin settings; entire-library sync without hash comparison still refreshes metadata and lyrics for known tracks; translations get separate language-tagged embeddings.

## Current status

Implemented: encrypted admin configuration with separate API and translation settings endpoints, validated OpenAI SDK requests, translation storage, sync backfill, optional audio hash verification, sync cancellation, clear-translations confirmation, fullscreen bilingual display, and indexed Browse filters.

Still pending: translated BGE embeddings and curation retrieval, per-request retry/rate-limit controls, and translation-specific failure handling. The worker currently treats translation failures as batch failures and can retry the entire batch. Changing the prompt does not invalidate existing translations; admins can clear translations after jobs stop and regenerate them.

With hash verification off, known Navidrome IDs reuse their existing identity. Replacing audio under the same ID can go undetected unless later analysis downloads and verifies it. Desktop translations appear alongside originals; mobile translations appear beneath them.

The sections below record the original design goals, not a claim that every item is complete.

## Data and API

- Add an instance-scoped configuration table for endpoint URL, enabled flag, model, prompt and source/target language pairs. Encrypt the API key with the existing credential encryption machinery. GET responses must return only `has_key`, never the key itself. Restrict mutations to admins. Reject non-HTTP(S) endpoints and disallow redirects to private or metadata networks unless explicitly allowing local endpoints; local OpenAI-compatible servers are a required use case, so document the network trust boundary. Never log headers, prompts or lyric bodies.
- Store translations separately from `lyrics`: track ID, source/target language tags, translated lines, source-text checksum, prompt revision and model, status/error timestamps. Unique key on track and language pair. Keep imported provider translations distinct from AI translations. Mark stale when source lyrics change; do not delete original lyrics.
- Expose available translations alongside lyrics in the player API with line mapping and language tags. A translation missing lines must not be treated as timed lyrics.

## Sync

- Pass an explicit `verify_audio_hashes` flag from the Entire library confirmation through the sync job payload and batches. The default remains on. With it off, catalog and source metadata must still be fetched; known source IDs reuse existing track identities and skip audio streaming/hash only. New IDs and changed IDs still require normal hashing. Do not silently merge changed audio under an old identity.
- Queue translation after source lyrics are resolved. Only process configured pairs matching detected source language and missing/stale translations. Rate-limit, bound per-song input and output, retry transient failures, and report translation failures without failing the entire sync. Send lyrics as untrusted data, request structured line-indexed JSON, validate indices and count, and never interpret lyric text as operational instructions. Entire-library sync without hash checks must include known tracks needing lyrics/translation work.

## UI

- Add admin-only External AI settings with an enable switch, URL, key replacement, model, prompt editor, and editable list of source/target language pairs. Warn that lyrics leave the instance for the configured endpoint.
- Redesign the Entire library dialog with an audio hash verification toggle and explicit descriptions of the identity risk and speed difference. No option should be called "skip all processing".
- Add a translation toggle near lyric size in fullscreen, only when a translation exists. Render each translated line beneath its source line at a smaller proportional size. Preserve original karaoke timing and avoid injecting translation into the timing engine. Persist the preference per browser.

## Retrieval

- Embed translated text as an independent representation with track ID, source and target languages, model revision, and translation checksum. Do not overwrite source-language lyrics embeddings. Include these in curation retrieval with explicit language/filter behavior and deduplicate tracks before ranking.

## Acceptance checks

- Admin-only key update/read redaction; disabled endpoint never called; invalid URL and SSRF cases; multiple pairs; missing, stale and unchanged translation cases; partial failure/retry; unchanged songs never downloaded in skip-hash mode; new/changed songs still hashed; fullscreen original/translated rendering at each size; translated embedding retrieval without duplicate tracks; migration and rollback safety.
