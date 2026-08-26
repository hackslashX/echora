CREATE TABLE IF NOT EXISTS analysis_settings (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  karaoke_bound_to_synced_lines boolean NOT NULL DEFAULT true,
  updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO analysis_settings (singleton) VALUES (true) ON CONFLICT DO NOTHING;

ALTER TABLE lyrics ADD COLUMN IF NOT EXISTS karaoke_bounded boolean;
UPDATE lyrics SET karaoke_bounded=false WHERE karaoke_model='fa_kara' AND karaoke_bounded IS NULL;
