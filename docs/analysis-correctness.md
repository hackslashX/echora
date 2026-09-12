# Ranking and representation contracts

## Curation scoring revision 4

Equal similarity scores receive the average of their ranks. A constant corpus, a single available score, and unavailable evidence remain at 0.5. Non-finite values do not participate in ranking.

A requested musical direction must meet the existing 0.75 library-relative cutoff. Curation no longer fills the remaining slots with below-threshold tracks. It can use remaining familiar matches when there are too few discovery matches, but it does not relax the relevance requirement. The familiar/discovery evidence reflects listening history rather than the slot used to select a track.

Recipes without a musical direction, such as language-only recipes, remain neutral and can select eligible tracks. A requested direction with missing or tied evidence does not count as an omitted direction.

Preview responses include requested count, selected count, and shortfall. An empty refresh fails before Navidrome publication and leaves the existing playlist unchanged. Nonempty playlists can be shorter than requested.

Percentiles are relative ranks, not match probabilities. Track evidence has `match_basis` and a null `match_confidence`; preview responses report `confidence_calibrated: false`. There is no new absolute acceptance threshold. That requires labeled relevant and irrelevant examples, including queries with no good library matches. The relative cutoff alone cannot reject every poor absolute match.

## Active representations

`representations.py` defines the configured embedding contracts. Startup registers them in `active_representation_specs`. Standalone ingestion, lyrics, voice, and profile backfills register the same deployment configuration before planning work.

`current_embeddings` selects the exact model revision, configuration hash, and dimension. `current_audio_profiles` also requires the active source representation and the active profile algorithm configuration. Curation, concepts, maps, artist similarity, journeys, and recording matching read these views rather than selecting an independently latest representation for each track.

Default audio and lyrics configurations preserve the hashes of existing compatible runs. Custom model repository IDs contribute to the configuration hash and require new representations. Changing a revision or preprocessing configuration reduces coverage until matching representations exist. Readers do not fall back to an incompatible older space. Historical data remains in the original tables.

This is a fail-closed policy, not a blue/green corpus rollout. Before changing production model revisions, plan the backfill or expect reduced availability. All processes sharing this database must use the same representation configuration. Background execution uses durable worker claims; interactive inference capacity still needs explicit deployment limits.

Curation previews and revisions retain the exact representation run IDs. Per-track evidence also retains its run IDs.

## Processing attempts

`analysis_runs` remains the reusable representation definition. Reusing it no longer resets its status or start time. Audio and lyrics embedding executions create separate `analysis_attempts` and `analysis_attempt_tracks` rows. Their status distinguishes complete, partial, failed, and interrupted execution.

Readers treat committed embedding and profile rows as completed per-track artifacts. They do not hide existing tracks while another track in the same representation is being processed. The writers commit each track's aggregate and window representations together. API startup does not mark other workers' attempts interrupted. Worker attempts link to their durable job; leaving a running claim marks any unfinished linked attempts interrupted. Retries replan from committed artifacts. Legacy unlinked attempt rows are not a substitute for the durable job lifecycle.

The old `analysis_runs.status` field is not a reliable batch-success indicator. Use `analysis_attempts` for audio and lyrics embedding outcomes. Other processing stages still report their existing summaries.

## Deployment and validation

Apply Alembic revisions `0031_representation_contracts` and `0032_audio_descriptors` through normal analysis startup. No production migration is part of the code change itself.

Database regression tests in `tests/test_representations.py` require `TEST_DATABASE_URL` pointing to a disposable database migrated to head. Without it, database tests skip. Do not point these tests at a live library.
