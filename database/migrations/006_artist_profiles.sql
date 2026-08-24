CREATE TABLE IF NOT EXISTS artist_profiles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  artist_key text NOT NULL,
  artist_name text NOT NULL,
  model_name text NOT NULL,
  corpus_hash text NOT NULL,
  track_count integer NOT NULL CHECK (track_count > 0),
  component_count integer NOT NULL CHECK (component_count > 0),
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (artist_key, model_name, corpus_hash)
);
CREATE INDEX IF NOT EXISTS artist_profiles_name_idx ON artist_profiles (lower(artist_name));
