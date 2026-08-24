CREATE TABLE IF NOT EXISTS community_snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  model_name text NOT NULL,
  semantic_weight double precision NOT NULL CHECK (semantic_weight BETWEEN 0 AND 1),
  corpus_hash text NOT NULL,
  algorithm_revision integer NOT NULL,
  track_count integer NOT NULL CHECK (track_count >= 0),
  parameters jsonb NOT NULL,
  metrics jsonb NOT NULL,
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (model_name, semantic_weight, corpus_hash, algorithm_revision)
);
CREATE INDEX IF NOT EXISTS community_snapshots_latest_idx
  ON community_snapshots (model_name, semantic_weight, created_at DESC);
