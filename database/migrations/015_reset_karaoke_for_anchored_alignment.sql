-- Discard whole-song FA-Kara results so the next sync rebuilds both variants
-- with source-timeline-anchored inference.
DELETE FROM karaoke_lyrics_variants;

UPDATE lyrics
SET karaoke_lines = NULL,
    karaoke_ass = NULL,
    karaoke_lrc = NULL,
    karaoke_model = NULL,
    karaoke_model_revision = NULL,
    karaoke_bounded = NULL,
    karaoke_created_at = NULL,
    provenance = provenance - 'karaoke'
WHERE karaoke_lines IS NOT NULL OR provenance ? 'karaoke';
