ALTER TABLE user_preferences
  ADD COLUMN IF NOT EXISTS animation_speed text NOT NULL DEFAULT 'normal'
  CHECK (animation_speed IN ('slow', 'normal', 'fast'));
