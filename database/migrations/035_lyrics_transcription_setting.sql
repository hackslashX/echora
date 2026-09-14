ALTER TABLE analysis_settings ADD COLUMN IF NOT EXISTS transcription_processing_enabled boolean NOT NULL DEFAULT false;
