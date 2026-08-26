ALTER TABLE lyrics ADD COLUMN IF NOT EXISTS karaoke_lines jsonb;
ALTER TABLE lyrics ADD COLUMN IF NOT EXISTS karaoke_ass text;
ALTER TABLE lyrics ADD COLUMN IF NOT EXISTS karaoke_lrc text;
ALTER TABLE lyrics ADD COLUMN IF NOT EXISTS karaoke_model text;
ALTER TABLE lyrics ADD COLUMN IF NOT EXISTS karaoke_model_revision text;
ALTER TABLE lyrics ADD COLUMN IF NOT EXISTS karaoke_created_at timestamptz;

CREATE INDEX IF NOT EXISTS lyrics_karaoke_pending_idx ON lyrics (track_id)
  WHERE text IS NOT NULL AND karaoke_lines IS NULL;
