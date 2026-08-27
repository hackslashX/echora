ALTER TABLE analysis_settings
  ADD COLUMN IF NOT EXISTS karaoke_processing_enabled boolean NOT NULL DEFAULT true;

UPDATE analysis_settings SET karaoke_bound_to_synced_lines=false;
DELETE FROM karaoke_lyrics_variants WHERE bounded=true;
