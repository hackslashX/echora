ALTER TABLE analysis_settings
  ADD COLUMN IF NOT EXISTS hum_processing_enabled boolean NOT NULL DEFAULT true;
