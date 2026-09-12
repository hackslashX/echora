# Durable jobs and workers

## Processes

The API submits jobs and exposes owner-scoped `GET /jobs`, `GET /jobs/{id}`, and `POST /jobs/{id}/cancel`. It does not scan catalogs or execute background pipelines. The sync page discovers active work for its connection without browser-stored job IDs.

Two worker types share PostgreSQL:

- `python -m echora_analysis.worker analysis`: sync, selected imports, analysis backfills and hum indexes.
- `python -m echora_analysis.worker scheduled`: due-curation polling and manual/scheduled curation refreshes.

Each worker process claims one job at a time and supervises an isolated executor subprocess. Multiple processes can claim different batches. Device selection remains in the existing model implementations; CPU and GPU use the same pipeline. Size worker counts for available RAM/VRAM: automatic CUDA detection is not resource admission control.

A sync scans the complete catalog before removing stale user links, then atomically expands into bounded child batches. Imports never remove unselected links. Each batch runs its required stages in sequence, loading each needed model once for that stage. `ECHORA_BATCH_SIZE` defaults to 32. The private disk audio cache defaults to 2 GiB per active executor (`ECHORA_AUDIO_CACHE_BYTES`); files beyond the limit are downloaded again rather than retained. Allow enough temporary disk space per worker.

## Recovery and results

Claims have renewable leases and unique tokens. Database writes to job state require the current unexpired token. Expired work retries up to three attempts with backoff. Pipeline failures that leave an incomplete batch also retry within that limit. Compatible committed artifacts are reused; inference is not exactly-once, and overlapping jobs can still perform duplicate computation.

Root jobs wait without holding a worker while their batches run. Progress is reported in batches, with terminal states `complete`, `partial`, `failed`, or `cancelled`. Audio and lyrics execution attempts link to their owning job; leaving a running claim marks any unfinished linked attempts interrupted. Other stages recover from their persisted artifacts and batch summaries, not a universal per-song task ledger.

Cancellation is cooperative and checked at pipeline progress/network boundaries. The supervisor also stops an executor and its process group when the lease cannot be renewed. Completed artifacts are not rolled back. On Linux, executors receive a termination signal if their supervisor dies. Forced host/process failure can leave temporary directories; periodic host temporary-file cleanup remains advisable.

Curation schedules coalesce missed intervals into one refresh rather than replaying every missed run. Per-curation database locks serialize publication and recipe mutation. A durable publication intent stores the exact selected order before remote I/O. Replacing a known playlist can replay that same intent. If an initial playlist creation has an unknown outcome, automatic creation stops to avoid duplicates; an operator must reconcile it with Navidrome. No automatic ambiguous-creation resolution UI is provided yet.

## Deployment

GPU defaults:

```sh
docker compose up --build -d
```

CPU-only (requires Docker Compose support for `!reset`):

```sh
docker compose -f compose.yaml -f compose.cpu.yaml up --build -d
```

Scale the two worker services independently, for example `--scale analysis-worker=2`. Workers run without public ports and wait for API health; API startup applies migrations through `0036_job_analysis_attempts`. Keep all processes on the same code and representation configuration. External deployments must migrate once before starting workers and must add both worker types; deploying just the API will leave jobs queued.

For the first rollout, drain or stop old in-process background work before migrating/replacing the API. Old volatile job IDs cannot be recovered. Completed artifacts remain reusable. Do not run old and new schedulers together. Redis remains a disposable media cache and is not the queue.

CPU-only configuration is supplied, but full model inference on CPU and real Navidrome publication require deployment-specific smoke testing. Automated tests exercise orchestration with mocked inference and a disposable PostgreSQL database. No live library migration is part of local validation.
