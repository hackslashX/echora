# Echora

Echora is a self-hosted, multi-user music analysis and discovery application for Navidrome libraries. It combines MuQ-MuLan semantic embeddings, MERT acoustic embeddings, BGE-M3 lyrics embeddings, recording fingerprints, listening history, and managed Navidrome playlists in one interface.

## Run locally

Requirements:

- Docker with Compose
- NVIDIA Container Toolkit for GPU analysis
- An OpenID Connect provider
- A Navidrome server

Create local configuration and replace every blank secret:

```sh
cp configs/env.example .env
openssl rand -base64 32  # OIDC_SESSION_SECRET
```

Generate `CREDENTIAL_ENCRYPTION_KEY` with Python:

```sh
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Build the analysis image and download the pinned model snapshots before starting model-dependent work:

```sh
docker compose build analysis
docker compose run --rm --no-deps -e HF_HUB_OFFLINE=0 analysis python -m echora_analysis.download_models
docker compose up --build
```

The snapshots currently use about 23 GB under `data/models/huggingface`. Compose mounts that directory at `/models/huggingface` and runs the application with `HF_HUB_OFFLINE=1`, so ingestion fails rather than silently downloading another model revision.

Open `http://localhost:3000`. The analysis health endpoint is `http://localhost:8000/health`.

Alembic initializes a new empty PostgreSQL database from the v1 baseline and applies every later revision during analysis startup.

## OIDC

Echora has no local password login. The normalized OIDC email claim is the immutable username, while the display name remains editable.

Register this local callback exactly:

```text
http://localhost:3000/analysis/auth/oidc/callback
```

`OIDC_BOOTSTRAP_ADMIN_EMAIL` must sign in first. That account becomes administrator. Automatic provisioning starts enabled and can be disabled under Settings. Administrators can approve individual emails, promote or demote users, and block accounts. Blocking immediately revokes active sessions.

`OIDC_REQUIRE_VERIFIED_EMAIL` defaults to `false`. Set it to `true` when the provider must attest the email claim.

## Development

Install JavaScript dependencies and run the web application:

```sh
npm install
npm run dev
```

Run the standard checks:

```sh
npm run typecheck
npm run lint
npm run build
```

Python tests run from the analysis environment:

```sh
pytest services/analysis/tests
```

## Database and models

PostgreSQL 17 needs these extensions:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

Track identity is SHA-256 of the source audio bytes, represented as a UUIDv5. Fingerprints group equivalent recordings without replacing canonical track identity. Model revisions are pinned in `compose.yaml` and `services/analysis/src/echora_analysis/download_models.py`.

Echora's source code uses the MIT license. Model weights keep their upstream licenses. MuQ-MuLan weights use CC-BY-NC-4.0, so review that license before use outside personal or research work. HeartCLAP remains excluded because there is no reproducible official public checkpoint and inference interface for the planned comparison.

## Deployment

The GitOps chart lives in the separate homelab repository at:

```text
lyra/projects/media/applications/echora
```

It deploys separate web and analysis workloads, downloads pinned models into a persistent volume with an init container, and keeps the running analysis container offline from Hugging Face. Production credentials belong in Vault, not this repository.

See `CONTEXT.md` for domain terms and `docs/adr/` for architectural decisions.
