CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE libraries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  root_path text NOT NULL,
  namespace uuid NOT NULL UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- A track is global and content-addressed. The same decoded file seen in two
-- libraries resolves to one row and one set of model embeddings.
CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  username text NOT NULL UNIQUE,
  display_name text NOT NULL,
  password_hash text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE user_preferences (
  user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  onboarding_complete boolean NOT NULL DEFAULT false,
  navidrome_connection_id uuid,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE user_sessions (
  token_hash text PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX user_sessions_expiry_idx ON user_sessions (expires_at);

CREATE TABLE navidrome_connections (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  url text NOT NULL,
  username text NOT NULL,
  encrypted_password bytea NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  last_used_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (url, username)
);

ALTER TABLE user_preferences
  ADD CONSTRAINT user_preferences_navidrome_connection_fk
  FOREIGN KEY (navidrome_connection_id) REFERENCES navidrome_connections(id) ON DELETE SET NULL;

CREATE TABLE tracks (
  id uuid PRIMARY KEY,
  audio_hash text NOT NULL UNIQUE,
  title text NOT NULL,
  artist text,
  album text,
  year integer,
  duration_seconds double precision NOT NULL CHECK (duration_seconds >= 0),
  genres text[] NOT NULL DEFAULT '{}',
  metadata jsonb NOT NULL DEFAULT '{}',
  ingested_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE library_tracks (
  library_id uuid NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
  track_id uuid NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
  relative_path text,
  added_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (library_id, track_id)
);

CREATE TABLE track_sources (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  library_id uuid NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
  track_id uuid NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
  source_type text NOT NULL CHECK (source_type IN ('filesystem', 'subsonic')),
  external_id text NOT NULL,
  source_data jsonb NOT NULL DEFAULT '{}',
  UNIQUE (library_id, source_type, external_id)
);

CREATE TABLE lyrics (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  track_id uuid NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
  source text NOT NULL CHECK (source IN ('embedded', 'local-file', 'transcribed', 'none')),
  text text,
  language text,
  confidence real CHECK (confidence BETWEEN 0 AND 1),
  provenance jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE analysis_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind text NOT NULL,
  model_name text,
  model_revision text,
  config_hash text NOT NULL,
  config jsonb NOT NULL,
  environment jsonb NOT NULL DEFAULT '{}',
  device text,
  precision text,
  status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'complete', 'failed', 'cancelled')),
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (kind, model_name, model_revision, config_hash)
);

CREATE TABLE embeddings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  track_id uuid NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
  run_id uuid NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
  embedding_type text NOT NULL CHECK (embedding_type IN ('audio-track', 'audio-window', 'lyrics')),
  window_index integer,
  window_start_seconds double precision,
  window_end_seconds double precision,
  dimension integer NOT NULL,
  aggregation text,
  embedding vector NOT NULL,
  inference_ms integer,
  peak_vram_bytes bigint,
  artifact_checksum text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE NULLS NOT DISTINCT (track_id, run_id, embedding_type, window_index)
);
CREATE INDEX embeddings_lookup_idx ON embeddings (run_id, embedding_type, track_id);

CREATE TABLE evaluation_queries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  text text NOT NULL,
  intent text NOT NULL,
  qualifies text NOT NULL,
  excludes text NOT NULL,
  split text NOT NULL DEFAULT 'evaluation' CHECK (split IN ('tuning', 'evaluation')),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE retrieval_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  query_id uuid NOT NULL REFERENCES evaluation_queries(id) ON DELETE CASCADE,
  run_id uuid NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
  track_id uuid NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
  rank integer NOT NULL CHECK (rank > 0),
  score double precision NOT NULL,
  latency_ms integer,
  review_batch uuid,
  UNIQUE (query_id, run_id, rank)
);

CREATE TABLE judgments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  result_id uuid NOT NULL REFERENCES retrieval_results(id) ON DELETE CASCADE,
  relevance smallint NOT NULL CHECK (relevance BETWEEN 0 AND 3),
  notes text,
  reviewer text NOT NULL DEFAULT 'owner',
  judged_at timestamptz NOT NULL DEFAULT now()
);
