"use client";

import { useEffect, useRef, useState } from "react";
import { isActiveJob, isTerminalJob, jobRequest, watchJob, type Job } from "./durableJobs";

export function useDurableJob(connectionId: string) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [dismissing, setDismissing] = useState(false);
  const dismissal = useRef<AbortController | null>(null);
  const [target, setTarget] = useState<{ connection: string; id: string } | null>(null);
  useEffect(() => {
    // Reset the subscription snapshot when its server scope changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setJob(null); setError(""); setLoading(!!connectionId); setDismissing(false);
    if (!connectionId) return;
    const stop = watchJob(connectionId, target?.connection === connectionId ? target.id : null, value => { setJob(value); setLoading(false); }, setError);
    return () => { stop(); dismissal.current?.abort(); dismissal.current = null; };
  }, [connectionId, target]);
  function track(id: string) { setTarget({ connection: connectionId, id }); }
  async function dismiss() {
    if (!isTerminalJob(job) || dismissal.current) return;
    const controller = new AbortController();
    dismissal.current = controller;
    setDismissing(true); setError("");
    try {
      await jobRequest(`/jobs/${encodeURIComponent(job!.job_id || job!.id!)}/dismiss`, controller.signal, "POST");
      if (!controller.signal.aborted) { setJob(null); setTarget(null); }
    } catch {
      if (!controller.signal.aborted) setError("Could not save dismissal. Please try again.");
    } finally {
      if (!controller.signal.aborted) { dismissal.current = null; setDismissing(false); }
    }
  }
  return { job, error, loading, dismissing, active: isActiveJob(job), terminal: isTerminalJob(job), track, dismiss };
}
