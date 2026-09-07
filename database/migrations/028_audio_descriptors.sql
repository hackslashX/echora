CREATE TABLE IF NOT EXISTS track_audio_descriptors (
  track_id uuid NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
  revision text NOT NULL,
  status text NOT NULL CHECK (status IN ('complete', 'partial')),
  descriptors jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (track_id, revision)
);

CREATE TABLE IF NOT EXISTS track_vocal_activity (
  track_id uuid NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
  run_id uuid NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
  activity jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (track_id, run_id)
);
