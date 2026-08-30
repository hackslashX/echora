ALTER TABLE curations
  DROP COLUMN IF EXISTS sound_prompt,
  DROP COLUMN IF EXISTS themes_prompt,
  DROP COLUMN IF EXISTS sound_weight;
ALTER TABLE curations
  ADD COLUMN IF NOT EXISTS sound_prompts text[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS themes_prompts text[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS sound_negative_prompts text[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS themes_negative_prompts text[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS sound_weight smallint NOT NULL DEFAULT 50;
