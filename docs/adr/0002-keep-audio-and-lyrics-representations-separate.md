# 0002: Keep audio and lyrics representations separate

Date: 2026-08-24
Status: accepted

## Context

Lyrics can improve thematic similarity, concepts, clustering, and recommendations. They are absent for some tracks, unreliable for others, and describe words rather than sound. Concatenating lyrics into every audio vector would exclude instrumentals or silently change the meaning of similarity when lyrics are missing.

## Decision

Echora stores lyrics documents and dedicated multilingual lyrics representations separately from MuQ-MuLan semantic-audio and MERT acoustic representations.

Lyrics-only analysis has its own neighbors, graph, projection, communities, concepts, metrics, and provenance. Combined queries use explicit late-fusion weights. A query must also state how it handles tracks without lyrics. Echora will not silently redistribute missing lyrics weight to audio.

MuQ-MuLan's text encoder remains the mechanism for comparing short concepts with audio. A dedicated long-text multilingual model will embed complete lyrics after chunking.

## Consequences

Instrumentals remain first-class tracks. Users can distinguish sonic similarity from lyrical similarity. Combined results require complete modality coverage or an explicit missing-data policy. Storage and evaluation costs increase because lyrics vectors and snapshots have independent model revisions and backfills.
