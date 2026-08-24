CREATE TABLE IF NOT EXISTS track_fingerprints (
  track_id uuid PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
  algorithm text NOT NULL,
  algorithm_version text NOT NULL,
  fingerprint bytea NOT NULL,
  duration_seconds double precision NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS recording_groups (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  status text NOT NULL DEFAULT 'automatic' CHECK (status IN ('automatic', 'confirmed', 'rejected')),
  canonical_track_id uuid REFERENCES tracks(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS recording_group_members (
  group_id uuid NOT NULL REFERENCES recording_groups(id) ON DELETE CASCADE,
  track_id uuid NOT NULL UNIQUE REFERENCES tracks(id) ON DELETE CASCADE,
  confidence double precision NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  membership_status text NOT NULL DEFAULT 'automatic' CHECK (membership_status IN ('automatic', 'confirmed', 'rejected')),
  added_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (group_id, track_id)
);

CREATE TABLE IF NOT EXISTS recording_match_evidence (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  left_track_id uuid NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
  right_track_id uuid NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
  decision text NOT NULL CHECK (decision IN ('matched', 'rejected', 'review')),
  chromaprint_score double precision,
  duration_delta_seconds double precision,
  semantic_similarity double precision,
  acoustic_similarity double precision,
  matcher_revision integer NOT NULL,
  evidence jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (left_track_id < right_track_id),
  UNIQUE (left_track_id, right_track_id, matcher_revision)
);
CREATE INDEX IF NOT EXISTS track_fingerprints_duration_idx ON track_fingerprints (duration_seconds);
CREATE INDEX IF NOT EXISTS recording_match_tracks_idx ON recording_match_evidence (left_track_id, right_track_id);
