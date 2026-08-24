# Architecture

Echora separates immutable track identity, recording equivalence, model representations, and user visibility.

## Services

The Next.js web service renders the interface and proxies `/analysis/*` to the Python service. The root `PlayerProvider` keeps playback and queues alive across routes.

The FastAPI analysis service owns OIDC sessions, application APIs, Navidrome synchronization and playback proxying, model inference, lyrics retrieval, clustering, curations, and scheduled work. One analysis replica is required until scheduler claims and playlist publication are safe under concurrency.

PostgreSQL 17 with pgvector is the canonical store. SQLAlchemy handles ordinary lifecycle queries. Reviewed PostgreSQL SQL remains in analytical paths where pgvector operations, CTEs, bulk reconciliation, or query plans need direct control. Alembic creates the v1 schema and applies every later revision during analysis startup.

## Identity and access

OIDC is the only login method. The normalized email claim is the immutable username and the provider subject binds the identity. Echora stores authorization, provisioning, blocking, preferences, and sessions locally. Credentials remain deployment-owned or encrypted at rest.

A track is identified by SHA-256 of its source bytes and a UUIDv5 derived from that digest. `user_track_links` determines which shared tracks each user can access. Synchronization removes stale links without deleting reusable metadata, fingerprints, or representations.

Chromaprint supplies evidence for non-destructive recording groups. A recording group never replaces canonical track identity.

## Representations

Echora stores MuQ-MuLan semantic audio, MERT acoustic audio, and BGE-M3 lyrics representations separately. Similarity blends combine normalized scores at query time. Missing lyrics have explicit behavior and never silently change the requested weights.

Pinned Hugging Face snapshots live outside the image. Production downloads missing snapshots into a persistent volume before analysis starts. The running service uses offline mode so a repository update cannot change inference without a configured revision change.

Communities are reproducible SNN-Leiden partitions of a fixed corpus. Concepts are overlapping textual associations and remain distinct from communities. Projection coordinates support presentation only and never define similarity.

## Curations

A curation is a durable recipe for a fully managed Navidrome playlist. Revisions preserve evidence, membership, ordering, achieved familiarity mix, and shuffle seed. Last.fm history determines recent familiarity and recurring local-time evidence. User timezone controls time-of-day assignment.

## Deployment

Production runs separate web and analysis deployments behind one ingress. The web service proxies analysis requests internally. PostgreSQL and model snapshots use persistent storage. The model init container has network access; the analysis container does not download model files at runtime.
