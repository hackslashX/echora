ALTER TABLE karaoke_lyrics_variants
  ADD COLUMN IF NOT EXISTS alignment_document JSONB,
  ADD COLUMN IF NOT EXISTS diagnostics JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE karaoke_lyrics_variants
  DROP CONSTRAINT IF EXISTS karaoke_alignment_document_schema;

ALTER TABLE karaoke_lyrics_variants
  ADD CONSTRAINT karaoke_alignment_document_schema CHECK (
    alignment_document IS NULL OR alignment_document->>'schema_version' = '1'
  );
