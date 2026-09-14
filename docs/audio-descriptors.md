# Measured audio descriptors

Audio descriptor revision 1 runs during Navidrome synchronization, independently of MuQ, MERT, and lyrics inference. It uses the existing Essentia dependency and does not download additional models.

Each track has a versioned record in `track_audio_descriptors`. Synchronization schedules missing or partial records. Completed records are reused. A failure in one Essentia component preserves other measurements and marks the record partial for retry.

## Measurements

The decoder supplies stereo 44.1 kHz audio. The pipeline stores:

- Integrated EBU R128 loudness in LUFS and loudness range in LU, for audio at least three seconds long.
- Sample peak and RMS level in dBFS. These are sample measurements, not true-peak measurements. `true_peak_dbtp` remains null.
- One-second energy windows with exact source ranges, including a short final window. Channel energy is measured before mono mixing, so out-of-phase stereo does not disappear from level measurements.
- Spectral centroid in Hz and positive normalized spectral flux, summarized over one-second windows. These describe timbral change; flux is not a calibrated onset or danceability score.
- Whole-track tempo, beat times, tempo estimates, and the raw Essentia multifeature confidence for audio at least ten seconds long. Half/double-tempo ambiguity remains explicit.
- Whole-track key and scale with raw profile-correlation strength. This does not analyze key changes or provide verse/chorus labels.

Silence produces null levels rather than JSON infinity, and no fabricated tempo or key. Short audio carries warnings for unavailable measurements. Confidence values are extractor evidence, not calibrated probabilities.

Curation sound profiles can use pace, energy, brightness, motion, vocal presence, and dynamics as library-relative soft ranking targets. Each available axis is percentile-ranked inside the user's visible library. The vocals axis is a low-to-high vocal-presence preference, not an instrumental-only request. The separate Instrumental only toggle is a hard filter: it keeps only tracks whose voice classifier reports instrumental confidence of at least 0.5; tracks without a voice classification do not qualify. Missing or insufficient measurements remove a soft-profile axis from a track's profile score rather than counting as a mismatch. Raw tempo, key, beat times, and loudness do not act as hard filters or control playlist order in this revision.

The record includes the descriptor revision, sample rate, duration, and Essentia version when used. Bump `DESCRIPTOR_REVISION` when changing measurement settings or algorithms.

## Vocal activity

The existing voice backfill now retains each classifier patch's vocal activation in `track_vocal_activity`, alongside its existing track-level voice classification. It reprocesses tracks that have a classification but lack the activity record. The backfill is scoped to its Navidrome server.

The stored source ranges reflect the existing 16 kHz, 128-frame patch preprocessing. The classifier does not process an incomplete trailing patch; `unanalyzed_tail_seconds` reports the uncovered tail. Tracks shorter than one patch retain the existing failure behavior. Activations are not singer identity, demographic ground truth, or calibrated vocal-presence probabilities.

Use the existing voice-backfill action to populate this optional artifact. Ordinary audio synchronization populates the measured descriptors without loading the voice model.

## API

Authenticated users can inspect a visible track:

```http
GET /library/tracks/{track_id}/audio-descriptors
```

The response includes descriptor status, measurements, optional vocal activity, and `used_in_curation: {"sound_profile": true}`. Missing measurements return `pending`. A track outside the user's visible library returns 404.

After deploying the migrations, run a normal Navidrome synchronization to backfill measurements. This adds one audio download and a CPU analysis pass for tracks without a completed descriptor record.
