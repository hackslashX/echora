-- Move animation speed to client-side storage.
ALTER TABLE user_preferences DROP COLUMN IF EXISTS animation_speed;
