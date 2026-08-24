ALTER TABLE lyrics ADD COLUMN IF NOT EXISTS availability_status text NOT NULL DEFAULT 'available';
ALTER TABLE lyrics DROP CONSTRAINT IF EXISTS lyrics_availability_status_check;
ALTER TABLE lyrics ADD CONSTRAINT lyrics_availability_status_check
  CHECK (availability_status IN ('available', 'missing', 'unavailable', 'instrumental'));
CREATE UNIQUE INDEX IF NOT EXISTS lyrics_track_idx ON lyrics (track_id);
CREATE INDEX IF NOT EXISTS lyrics_language_idx ON lyrics (language) WHERE text IS NOT NULL;
