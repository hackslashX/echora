# MERT hum search experiment

Branch: `feat/mert-hum-search`

## Scope

This experiment samples 50 tracks from the signed-in user's Navidrome catalog. It stores overlapping local MERT windows and compares a browser microphone recording against those windows. The browser records and uploads audio but does not extract features.

## Current implementation

- [x] Separate feature branch
- [x] Hum corpus and corpus membership schema
- [x] Random 50-track Navidrome corpus job
- [x] Ten-second MERT windows with a five-second stride
- [x] Per-window pgvector storage with track offsets
- [x] Authenticated corpus status, build, and search endpoints
- [x] Browse search microphone control
- [x] Best-window result ranking and matched timestamp
- [ ] Run migrations and build a real 50-track corpus
- [ ] Record evaluation queries and measure top 1, top 5, and top 10 recall
- [ ] Decide whether MERT cross-domain matching is accurate enough

## API

- `GET /library/hum/index`
- `POST /library/hum/index?track_limit=50`
- `POST /library/hum/search?limit=10` with encoded audio as the request body

## Known experimental limits

MERT still mean-pools frames inside each ten-second window. The change only removes the second aggregation across distant track windows. A hummed voice and a produced recording may remain far apart in MERT space. The evaluation must test that assumption before this becomes a production feature.

The current index scans a small corpus directly. It does not create an approximate pgvector index. Rebuilding creates a new corpus and leaves older corpora available for provenance until explicitly cleaned up.
