CREATE TABLE IF NOT EXISTS user_track_links (
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  library_id uuid NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
  track_id uuid NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
  external_id text NOT NULL,
  linked_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, library_id, track_id),
  UNIQUE (user_id, library_id, external_id)
);

CREATE INDEX IF NOT EXISTS user_track_links_track_idx
  ON user_track_links (user_id, track_id);

-- Preserve current visibility. The next synchronization reconciles this set
-- against the user's live Navidrome catalog.
INSERT INTO user_track_links (user_id, library_id, track_id, external_id)
SELECT ul.user_id, ul.library_id, ts.track_id, ts.external_id
FROM user_libraries ul
JOIN track_sources ts ON ts.library_id=ul.library_id
WHERE ts.source_type='subsonic'
ON CONFLICT DO NOTHING;
