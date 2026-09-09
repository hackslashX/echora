CREATE TABLE IF NOT EXISTS track_waveforms (
  track_id uuid PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
  revision text NOT NULL,
  duration_seconds double precision NOT NULL CHECK (duration_seconds > 0),
  peaks jsonb NOT NULL CHECK (jsonb_typeof(peaks) = 'array'),
  created_at timestamptz NOT NULL DEFAULT now()
);
