"use client";

import { useEffect, useRef, useState } from "react";
import { isActiveJob, jobRequest, type Job } from "./durableJobs";

/** Discover scheduled/other-tab refreshes as well as tracking POST acknowledgements. */
export function useCurationJobs(connectionId: string, reload: (signal: AbortSignal) => Promise<void>) {
  const reloadRef = useRef(reload);
  useEffect(() => { reloadRef.current = reload; });
  const pending = useRef(new Set<string>());
  const [error, setError] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]);
  useEffect(() => {
    // Reset the subscription snapshot when its server scope changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    pending.current.clear(); setJobs([]); setError("");
    if (!connectionId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const body = await jobRequest<{ jobs: Job[] }>(`/jobs?connection_id=${encodeURIComponent(connectionId)}&active_only=true`, controller.signal);
        for (const job of body.jobs) if (job.curation_id || job.kind === "curation_refresh") pending.current.add(job.job_id || job.id!);
        const current: Job[] = [];
        for (const id of [...pending.current]) {
          const job = await jobRequest<Job>(`/jobs/${encodeURIComponent(id)}`, controller.signal);
          if (isActiveJob(job)) current.push(job);
          else {
            // Keep it pending until the curation reload succeeds, so reload errors retry too.
            await reloadRef.current(controller.signal);
            pending.current.delete(id);
          }
        }
        if (!controller.signal.aborted) { setJobs(current); setError(""); }
      } catch (reason) {
        if (!controller.signal.aborted) setError(`Connection error: ${reason instanceof Error ? reason.message : "Could not refresh curations"}. Retrying…`);
      }
      if (!controller.signal.aborted) timer = setTimeout(poll, 1500);
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [connectionId]);
  return { jobs, error, track: (id?: string) => { if (id) pending.current.add(id); } };
}
