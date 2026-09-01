ALTER TABLE curations DROP CONSTRAINT IF EXISTS curations_type_check;
ALTER TABLE curations
  ADD CONSTRAINT curations_type_check
  CHECK (curation_type IN ('combined', 'language', 'examples', 'time_of_day'));
ALTER TABLE curations
  ADD COLUMN IF NOT EXISTS time_of_day_enabled boolean NOT NULL DEFAULT false;

