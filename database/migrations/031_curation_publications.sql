ALTER TABLE curations DROP CONSTRAINT curations_status_check;
        ALTER TABLE curations ADD CONSTRAINT curations_status_check
            CHECK (status IN ('draft', 'pending', 'refreshing', 'ready', 'failed'));
        CREATE TABLE curation_publications (
            id uuid PRIMARY KEY,
            curation_id uuid NOT NULL REFERENCES curations(id) ON DELETE CASCADE,
            job_id uuid NOT NULL,
            state text NOT NULL CHECK (state IN ('prepared', 'publishing', 'complete')),
            plan jsonb NOT NULL,
            playlist_id text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX curation_publications_pending ON curation_publications(curation_id)
            WHERE state <> 'complete';
        CREATE UNIQUE INDEX curation_publications_job ON curation_publications(job_id);
