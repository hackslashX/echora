CREATE TABLE IF NOT EXISTS concepts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid REFERENCES users(id) ON DELETE CASCADE,
  name text NOT NULL,
  description text NOT NULL DEFAULT '',
  positive_prompts text[] NOT NULL,
  negative_prompts text[] NOT NULL DEFAULT '{}',
  positive_track_ids uuid[] NOT NULL DEFAULT '{}',
  negative_track_ids uuid[] NOT NULL DEFAULT '{}',
  enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (cardinality(positive_prompts) + cardinality(positive_track_ids) > 0)
);
CREATE UNIQUE INDEX IF NOT EXISTS concepts_user_name_idx
  ON concepts (user_id, lower(name)) NULLS NOT DISTINCT;

CREATE TABLE IF NOT EXISTS concept_scores (
  concept_id uuid NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
  track_id uuid NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
  run_id uuid NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
  raw_score double precision NOT NULL,
  percentile double precision NOT NULL CHECK (percentile BETWEEN 0 AND 1),
  scored_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (concept_id, track_id, run_id)
);
CREATE INDEX IF NOT EXISTS concept_scores_track_idx ON concept_scores (track_id, run_id);
