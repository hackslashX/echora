CREATE TABLE IF NOT EXISTS curations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  navidrome_connection_id uuid NOT NULL REFERENCES navidrome_connections(id) ON DELETE CASCADE,
  name text NOT NULL,
  positive_prompt text NOT NULL,
  negative_prompt text NOT NULL DEFAULT '',
  track_limit integer NOT NULL DEFAULT 30 CHECK (track_limit BETWEEN 5 AND 200),
  refresh_mode text NOT NULL DEFAULT 'stable' CHECK (refresh_mode IN ('stable', 'fresh')),
  refresh_enabled boolean NOT NULL DEFAULT true,
  refresh_interval_hours integer NOT NULL DEFAULT 6 CHECK (refresh_interval_hours = 6),
  navidrome_playlist_id text,
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'refreshing', 'ready', 'failed')),
  last_error text,
  last_refreshed_at timestamptz,
  next_refresh_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS curations_user_name_idx
  ON curations (user_id, lower(name));

CREATE INDEX IF NOT EXISTS curations_due_idx
  ON curations (next_refresh_at)
  WHERE refresh_enabled;

CREATE TABLE IF NOT EXISTS curation_revisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  curation_id uuid NOT NULL REFERENCES curations(id) ON DELETE CASCADE,
  revision_number integer NOT NULL,
  recipe jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (curation_id, revision_number)
);

CREATE TABLE IF NOT EXISTS curation_revision_tracks (
  revision_id uuid NOT NULL REFERENCES curation_revisions(id) ON DELETE CASCADE,
  position integer NOT NULL CHECK (position >= 0),
  track_id uuid NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
  score real NOT NULL,
  evidence jsonb NOT NULL DEFAULT '{}',
  source_id text NOT NULL,
  PRIMARY KEY (revision_id, position),
  UNIQUE (revision_id, track_id)
);

CREATE INDEX IF NOT EXISTS curation_revision_tracks_track_idx
  ON curation_revision_tracks (track_id);
