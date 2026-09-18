ALTER TABLE lyrics DROP CONSTRAINT IF EXISTS lyrics_source_check;
ALTER TABLE lyrics ADD CONSTRAINT lyrics_source_check
  CHECK (source IN ('embedded', 'local-file', 'transcribed', 'manual', 'none'));
