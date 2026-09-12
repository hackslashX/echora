export type Job = { id?: string; kind?: string; parent_id?: string; job_id: string; connection_id?: string; curation_id?: string; status: string; phase: string; completed: number; total: number; message?: string; error?: string; cancel_requested?: boolean; unit?: string; track?: { id: string; title: string; artist?: string }; summary?: Record<string, number> };
export const isActiveJob = (job: Job | null) => !!job && ["queued", "running", "waiting"].includes(job.status);
export const isTerminalJob = (job: Job | null) => !!job && ["complete", "partial", "failed", "cancelled"].includes(job.status);
export async function jobRequest<T>(path: string, signal: AbortSignal, method = "GET"): Promise<T> {
  const response = await fetch(`/analysis${path}`, { signal, method });
  const body = await response.json();
  if (!response.ok) throw new Error(body?.detail || `Request failed (${response.status})`);
  return body as T;
}
export async function discoverJob(connectionId: string, signal: AbortSignal): Promise<Job | null> {
  const query = new URLSearchParams({ connection_id: connectionId });
  // Curation work must never be presented as library synchronization.
  for (const active of [true, false]) {
    const { jobs } = await jobRequest<{ jobs: Job[] }>(`/jobs?${query}&active_only=${active}`, signal);
    const job = jobs.find(item => !item.curation_id && item.kind !== "curation_refresh" && !item.parent_id);
    if (job) return job;
  }
  return null;
}

/** One in-flight request at a time; failures keep the same job and retry. */
export function watchJob(connectionId: string, jobId: string | null, receive: (job: Job | null) => void, onError: (message: string) => void, delay = 1200) {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout>;
  let id = jobId;
  async function poll() {
    let again = true;
    try {
      const job = id ? await jobRequest<Job>(`/jobs/${encodeURIComponent(id)}`, controller.signal) : await discoverJob(connectionId, controller.signal);
      if (controller.signal.aborted) return;
      receive(job); onError("");
      id = job?.job_id || job?.id || null;
      again = isActiveJob(job);
    } catch (reason) {
      if (controller.signal.aborted) return;
      onError(`Connection error: ${reason instanceof Error ? reason.message : "Could not read job progress"}. Retrying…`);
    }
    if (again && !controller.signal.aborted) timer = setTimeout(poll, delay);
  }
  void poll();
  return () => { controller.abort(); clearTimeout(timer); };
}
