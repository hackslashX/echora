CREATE INDEX IF NOT EXISTS tracks_title_sort_idx
  ON tracks (lower(title), lower(coalesce(artist, '')), id);

CREATE INDEX IF NOT EXISTS tracks_artist_sort_idx
  ON tracks (lower(artist), lower(title), id)
  WHERE artist IS NOT NULL;

CREATE INDEX IF NOT EXISTS tracks_release_sort_idx
  ON tracks (year DESC NULLS LAST, lower(title), id);

CREATE INDEX IF NOT EXISTS track_sources_track_lookup_idx
  ON track_sources (track_id, source_type, library_id, external_id);
