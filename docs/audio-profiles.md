# Versioned multi-vector audio profiles

Audio profiles are derived artifacts built independently from stored MuQ-MuLan and MERT window
embeddings. They do not run either model again and do not currently change Galaxy placement or
clustering. Curation scoring revision 3 consumes them when they are available.

Each profile records its source model, `audio_embedding` run, and `audio_profile` algorithm run. A
new source run or profile revision produces a distinct artifact, so results remain attributable to
both the model preprocessing and the derivation algorithm. MuQ-MuLan and MERT profiles always
remain in their own vector spaces.

## Representations

- `global_overlap_embedding` reproduces the normalized mean of every stored window.
- `global_decorrelated_embedding` averages a greedy non-overlapping subset for evaluation.
- Temporal segments are contiguous ranges selected with penalized spherical change points.
- Musical modes are recurring identities found by spherical k-means over the decorrelated subset.
  Every original overlapping window is subsequently assigned to its closest mode.

Modes are intentionally unlabeled. A textual concept layer can be added independently later.

Both source pipelines decode mono audio at 24 kHz, cover the full track with 10-second windows at
a five-second stride, normalize each window representation, retain it, and calculate a normalized
track mean. MERT additionally mean-pools its frame axis inside each window because its encoder emits
a temporal sequence; MuQ-MuLan already emits one clip vector. That model-specific distinction is
preserved rather than forcing the incompatible vector spaces together.

## Timestamps

New audio ingestion writes `window_start_seconds` and `window_end_seconds`. Profiles derived from
older runs reconstruct ranges from the source run's duration, window, and stride configuration and
return `timestamps_exact: false`.

## API

Authenticated users can inspect coverage:

```http
GET /library/audio-profiles/status
```

Start a background derivation for both representations available to the user's visible tracks:

```http
POST /library/audio-profiles/rebuild
```

The returned job ID can be polled at `GET /jobs/{job_id}`. Inspect one completed artifact with:

```http
GET /library/tracks/{track_id}/audio-profile?model=muq_mulan
GET /library/tracks/{track_id}/audio-profile?model=mert
```

The track response omits the stored vectors and returns provenance, diagnostics, temporal ranges,
mode weights, and representative window indexes.

## Revision 1 tuning status

Revision 1 parameters are evaluation defaults, not validated production thresholds. Curation uses
the derived modes conservatively and falls back per track when a current profile is absent. Segment
and mode penalties should still be tuned against representative short songs, long-form music, live
recordings, and stylistically heterogeneous tracks before increasing their ranking weight.

## Curation scoring revision 3

Sound tags remain MuQ-MuLan text-to-audio comparisons. When a current MuQ profile is available,
the tag score is 75% global and 25% duration-weighted modes. MERT is never compared to text.
The same duration-aware MuQ calculation applies to legacy free-form sound directions.

Selecting a language does not create an embedding prompt. Language detection supplies the hard or
soft language constraint, while musical scoring only uses sound directions, theme directions, or
example tracks actually supplied by the user. A language-only recipe therefore has neutral musical
scores; missing example and embedding channels are omitted rather than scored as zero.

Songs-like and songs-not-like evidence works in language, examples, and time-of-day curations. Its
available components are renormalized per candidate:

```text
50% MuQ-MuLan global
20% MuQ-MuLan mode transport
20% MERT global
10% MERT mode transport
```

Mode transport conserves each mode's duration weight. The strongest individual passage match is
reported as evidence but receives no independent ranking weight. Example evidence is a separate
soft-AND requirement alongside sound tags rather than being averaged into a text-query center.

Language, explicit examples, and time-of-day history are composable. Explicit examples and the
listening-period reference set remain independent score terms. Active sound and theme directions
collectively receive one unit of nominal weight, explicit examples receive one, and time-of-day
history receives one. The active weights are normalized to sum to one; an omitted aspect contributes
neither a zero nor denominator weight. Language is applied separately as a filter, priority, or
small affinity boost according to its strictness.
