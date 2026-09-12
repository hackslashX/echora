"use client";

import { useEffect, useRef, useState } from "react";
import { isActiveJob, isTerminalJob, jobRequest, watchJob, type Job } from "./durableJobs";

export function useDurableJob(connectionId: string) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [target, setTarget] = useState<{ connection: string; id: string } | null>(null);
  const cancelController = useRef<AbortController | null>(null);
  const [cancelling, setCancelling] = useState(false);
  useEffect(() => {
    // Reset the subscription snapshot when its server scope changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setJob(null); setError(""); setLoading(!!connectionId); setCancelling(false);
    if (!connectionId) return;
    const stop = watchJob(connectionId, target?.connection === connectionId ? target.id : null, value => { setJob(value); setLoading(false); }, setError);
    return () => { stop(); cancelController.current?.abort(); };
  }, [connectionId, target]);
  function track(id: string) { setTarget({ connection: connectionId, id }); }
  async function cancel() {
    if (!job || cancelling) return;
    const controller = new AbortController(); cancelController.current = controller; setCancelling(true);
    try {
      const value = await jobRequest<Job>(`/jobs/${encodeURIComponent(job.job_id || job.id!)}/cancel`, controller.signal, "POST");
      if (!controller.signal.aborted) { setJob(value); setError(""); }
    } catch (reason) { if (!controller.signal.aborted) setError(`Could not cancel: ${reason instanceof Error ? reason.message : "Connection error"}`); }
    finally { if (!controller.signal.aborted) setCancelling(false); }
  }
  return { job, error, loading, active: isActiveJob(job), terminal: isTerminalJob(job), track, cancel, cancelling, dismiss: () => { if (isTerminalJob(job)) setJob(null); } };
}
