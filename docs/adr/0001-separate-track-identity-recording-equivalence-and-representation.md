# 0001: Separate track identity, recording equivalence, and representation

Date: 2026-08-23
Status: accepted

## Context

The same recording can exist as several files, encodes, or sources. Audio fingerprints and model embeddings can detect that relationship, but both can change with extraction settings or model revisions. Merging rows around either signal would make identity unstable and could erase meaningful editions.

## Decision

Echora keeps three separate concepts:

1. A track is identified from its media bytes using the existing SHA-256 and UUIDv5 process.
2. A recording group relates tracks believed to contain the same recording. Membership is non-destructive and retains evidence.
3. Model representations belong to analysis runs and may change without changing track identity or recording-group history.

Embedding similarity may propose or support a recording match. It cannot establish canonical track identity.

## Consequences

Tracks remain addressable and playable independently. A model upgrade does not remint track IDs. Recording equivalence can be reviewed or reversed. Queries that want one result per recording must explicitly collapse recording groups rather than relying on track identity.
