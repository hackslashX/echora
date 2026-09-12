ALTER TABLE analysis_attempts ADD COLUMN job_id uuid REFERENCES jobs(id);
CREATE INDEX analysis_attempts_job ON analysis_attempts(job_id) WHERE job_id IS NOT NULL;

CREATE FUNCTION interrupt_job_analysis_attempts() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status = 'running' AND NEW.status <> 'running' THEN
    UPDATE analysis_attempts SET status='interrupted', finished_at=now()
      WHERE job_id=NEW.id AND status='running';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER jobs_interrupt_attempts AFTER UPDATE OF status ON jobs
  FOR EACH ROW EXECUTE FUNCTION interrupt_job_analysis_attempts();
