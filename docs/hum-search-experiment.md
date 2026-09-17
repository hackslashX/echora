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

MELODIA may follow a vocal, guitar, synth, or another salient line instead of the tune a listener remembers. Current indexing extracts contours from the full mix, shared Roformer overlap-2 vocals and accompaniment derived as mix minus vocals. It no longer runs Demucs. Matching still needs evaluation with real humming queries; preferred separation audio does not establish better search recall.

Melody source preparation shares the persistent cache used by transcription and karaoke. A new contour revision identifies the Roformer/residual recipe, and active search excludes earlier revisions. Refresh the index through a melody-index job or an enabled entire-library sync after deployment. Earlier contours stay in storage for provenance. No automatic deletion or library-wide reprocessing runs at startup. See [shared audio preprocessing](audio-preprocessing.md).
