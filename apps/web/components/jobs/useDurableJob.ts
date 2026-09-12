"use client";

import { useEffect, useState } from "react";
import { isActiveJob, isTerminalJob, watchJob, type Job } from "./durableJobs";

export function useDurableJob(connectionId: string) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [target, setTarget] = useState<{ connection: string; id: string } | null>(null);
  useEffect(() => {
    // Reset the subscription snapshot when its server scope changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setJob(null); setError(""); setLoading(!!connectionId);
    if (!connectionId) return;
    const stop = watchJob(connectionId, target?.connection === connectionId ? target.id : null, value => { setJob(value); setLoading(false); }, setError);
    return stop;
  }, [connectionId, target]);
  function track(id: string) { setTarget({ connection: connectionId, id }); }
  return { job, error, loading, active: isActiveJob(job), terminal: isTerminalJob(job), track, dismiss: () => { if (isTerminalJob(job)) setJob(null); } };
}
