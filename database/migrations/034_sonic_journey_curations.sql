-- Sonic journey curations: ordered waypoints through embedding space.
ALTER TABLE curations DROP CONSTRAINT curations_type_check;
ALTER TABLE curations ADD CONSTRAINT curations_type_check
  CHECK (curation_type = ANY (ARRAY['combined'::text, 'language'::text, 'examples'::text,
    'time_of_day'::text, 'sonic_journey'::text]));
ALTER TABLE curations
  ADD COLUMN IF NOT EXISTS journey_start_track_id uuid REFERENCES tracks(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS journey_stop_track_ids uuid[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS journey_end_track_id uuid REFERENCES tracks(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS journey_lyrics_weight smallint NOT NULL DEFAULT 25;
