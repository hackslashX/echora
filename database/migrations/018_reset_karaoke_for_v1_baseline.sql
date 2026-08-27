-- Promote the validated unbounded karaoke pipeline to the stable v1 baseline.
-- Existing generated timing belongs to experimental revision names and must be
-- regenerated explicitly by the next library sync.
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
