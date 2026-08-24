# ADR 0004: Build curations from relevance and recent listening

## Status

Accepted

## Context

Pure embedding rank produced coherent but impersonal playlists. Pure play-count rank would repeat favorites without respecting a language recipe or providing discovery. Time-of-day recipes also need evidence tied to the user's local clock rather than the server timezone.

## Decision

Every listening-aware curation has a configurable familiarity percentage and a lookback window of seven days by default.

The familiar pool contains recipe-relevant tracks played during the lookback window. Play frequency adds a bounded 15% ranking boost, so frequency cannot fully replace recipe relevance.

The discovery pool contains recipe-relevant tracks with no plays anywhere in the lookback window. Time-of-day curations derive their relevance target from tracks played inside the selected recurring local-time period. Their discovery pool still excludes tracks played elsewhere during the lookback window.

Echora fills the requested familiar and discovery quotas when enough candidates exist, respects the two-tracks-per-artist limit, fills shortages from the remaining ranked corpus, then shuffles the final membership. Each revision records its random seed, achieved mix, listen counts, and evidence.

Last.fm supplies listening events. Echora resolves events to visible Navidrome tracks by normalized artist and title, with a unique-title fallback. User timezone controls time-period assignment, including periods that cross midnight.

## Consequences

Refreshes remain relevant to their recipe while mixing known and unplayed-recently tracks. Exact requested percentages may not be possible when a pool is too small. Revision evidence records the achieved result instead of pretending the target was met.

Last.fm metadata mismatches can leave some listens unresolved. The API reports matched-listen counts so this loss is visible.
