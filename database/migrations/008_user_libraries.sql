CREATE TABLE IF NOT EXISTS user_libraries (
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  library_id uuid NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
  added_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, library_id)
);

CREATE INDEX IF NOT EXISTS user_libraries_library_idx
  ON user_libraries (library_id, user_id);

-- Preserve visibility for users whose selected Navidrome connection already
-- resolves to a shared library.
INSERT INTO user_libraries (user_id, library_id)
SELECT preferences.user_id, libraries.id
FROM user_preferences AS preferences
JOIN navidrome_connections AS connections
  ON connections.id = preferences.navidrome_connection_id
JOIN libraries
  ON lower(rtrim(libraries.root_path, '/')) = lower(rtrim(connections.url, '/'))
ON CONFLICT DO NOTHING;
