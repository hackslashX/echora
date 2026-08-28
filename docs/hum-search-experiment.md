# Melody contour hum search experiment

Branch: `feat/mert-hum-search`

## Scope

This experiment samples 50 tracks from the signed-in user's Navidrome catalog. Essentia MELODIA extracts the predominant melody from each studio recording. The server extracts monophonic pitch from the browser recording with pYIN, removes the query key, and uses tempo-tolerant subsequence dynamic time warping. The browser only records and uploads audio.

## Current implementation

- [x] Separate feature branch
- [x] Hum corpus and corpus membership schema
- [x] Random 50-track Navidrome corpus job
- [x] Predominant melody extraction from full studio recordings
- [x] Ten-hertz pitch contour storage with voiced frames
- [x] Key-independent matching with tempo-tolerant subsequence DTW
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

MELODIA may follow a vocal, guitar, synth, or another salient line instead of the tune a listener remembers. The first contour version uses the full mix and does not yet compare a Demucs vocal contour. Matching scans the 50-track corpus directly. Rebuilding creates a new corpus and leaves older corpora available for provenance until explicitly cleaned up.
