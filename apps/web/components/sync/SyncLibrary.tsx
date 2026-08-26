"use client";

import { Check, Database, RefreshCw, Server, Waves } from "lucide-react";
import { useEffect, useState } from "react";
import AppShell from "../shell/AppShell";
import CopyrightFooter from "../shell/CopyrightFooter";
import { trackTemplate } from "../shell/gridGeometry";
import styles from "./SyncLibrary.module.css";

type Track = { id: string; title: string; artist?: string; album?: string };
type Status = { server: string; total: number; processed: number; missing: number; tracks: Track[] };
type Job = { job_id: string; status: "queued" | "running" | "complete" | "failed"; phase: string; message?: string; completed: number; total: number; unit?: "models" | "tracks"; error?: string; track?: Track; summary?: Record<string, number> };

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/analysis${path}`, options); const body = await response.json();
  if (!response.ok) throw new Error(body.detail || "The request failed"); return body as T;
}

export default function SyncLibrary() {
  const [connectionId, setConnectionId] = useState("");
  const [status, setStatus] = useState<Status | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [mode, setMode] = useState<"all" | "missing">("all");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");

  function scan(connection: string) {
    setBusy(true); setError("");
    api<Status>(`/navidrome/connections/${connection}/sync/status`).then(setStatus).catch(reason => setError(reason.message)).finally(() => setBusy(false));
  }

  useEffect(() => {
    fetch("/analysis/auth/me").then(response => response.json()).then(user => {
      const connection = user.navidrome_connection_id || ""; setConnectionId(connection);
      if (connection) scan(connection); else { setError("No Navidrome connection is configured"); setBusy(false); }
      const savedJob = sessionStorage.getItem("echora:sync-job");
      if (savedJob) api<Job>(`/jobs/${savedJob}`).then(setJob).catch(() => sessionStorage.removeItem("echora:sync-job"));
    }).catch(() => { setError("Could not load your connection"); setBusy(false); });
  }, []);

  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    const timer = window.setTimeout(() => api<Job>(`/jobs/${job.job_id}`).then(setJob).catch(reason => setError(reason.message)), 1200);
    return () => window.clearTimeout(timer);
  }, [job]);

  useEffect(() => {
    if (job?.status !== "complete" || !connectionId) return;
    sessionStorage.removeItem("echora:sync-job");
    const timer = window.setTimeout(() => scan(connectionId), 400);
    return () => window.clearTimeout(timer);
  }, [connectionId, job?.status]);

  async function start() {
    if (!connectionId) return; setBusy(true); setError("");
    try {
      const result = await api<{ job_id?: string; status: string; total: number; message?: string; summary?: Record<string, number> }>(`/navidrome/connections/${connectionId}/sync`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ mode }) });
      if (result.job_id) { sessionStorage.setItem("echora:sync-job", result.job_id); setJob({ job_id: result.job_id, status: "queued", phase: "queued", completed: 0, total: result.total }); }
      else setJob({ job_id: "", status: "complete", phase: "complete", message: result.message, completed: 0, total: 0, summary: result.summary });
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not start synchronization"); }
    finally { setBusy(false); }
  }

  const active = job && ["queued", "running"].includes(job.status);
  const percent = job?.total ? Math.round(job.completed / job.total * 100) : 0;
  const columns = [0.32, 0.04, 0.64];
  const rows = [1];
  return <AppShell title="Sync" footer={<CopyrightFooter />} breadcrumb flush fullPage grid={{ columns, rows }}>
    <main className={styles.page} style={{ gridTemplateColumns: trackTemplate(columns, 180), gridTemplateRows: trackTemplate(rows, 152) }}>
      <section className={styles.intro}><h1>Sync,<br /><em>step by step.</em></h1><p>Sync reads your server without changing its library. Echora keeps existing analysis and processes only the work each track still needs.</p><ol className={styles.steps}><li><b>1</b><div><strong>Read the catalog</strong><small>Load track IDs, metadata, artwork references, and the current library count from Navidrome.</small></div></li><li><b>2</b><div><strong>Resolve track identity</strong><small>Stream the source audio and use its SHA-256 content hash to link duplicates without merging recordings.</small></div></li><li><b>3</b><div><strong>Analyze missing representations</strong><small>MuQ-MuLan maps musical meaning, MERT measures acoustic structure, and BGE-M3 maps lyric language and themes. FA-Kara converts existing time-synced lyrics into syllable-level karaoke timing.</small></div></li><li><b>4</b><div><strong>Commit the results</strong><small>Store embeddings, karaoke lyrics, and provenance, then make the tracks available to Browse, Galaxy, concepts, journeys, and the player.</small></div></li></ol><div className={styles.server}><Server /><div><small>Connected server</small><strong>{status?.server || "Reading connection"}</strong></div></div></section>
      <section className={styles.workspace}>
        <header><div><h2>{active ? "Processing library" : busy ? "Scanning Navidrome" : "Library scan complete"}</h2></div><button onClick={() => connectionId && scan(connectionId)} disabled={busy || !!active}><RefreshCw /> RESCAN</button></header>
        <div className={styles.metrics}><div><Database /><strong>{status?.total ?? "—"}</strong><span>Navidrome tracks</span></div><div><Check /><strong>{status?.processed ?? "—"}</strong><span>Already indexed</span></div><div><Waves /><strong>{status?.missing ?? "—"}</strong><span>New tracks</span></div></div>
        {active || job?.status === "complete" || job?.status === "failed" ? <section className={styles.progress}><div><span>{job?.phase?.toUpperCase()}</span><strong>{job?.message || (job?.track ? `${job.track.artist || "Unknown artist"} · ${job.track.title}` : "Preparing models")}</strong><small>{job?.completed || 0} of {job?.total || 0} {job?.unit || "tracks"}</small></div><b>{percent}%</b><i><u style={{ width: `${percent}%` }} /></i>{job?.status === "failed" && <p>{job.error}</p>}{job?.status === "complete" && <div className={styles.summary}><span>{job.summary?.inserted || 0} new</span><span>{job.summary?.already_linked || 0} reused</span><span>{job.summary?.failed || 0} failed</span><span>{job.summary?.lyrics_embedded || 0} lyrics embedded</span><span>{job.summary?.karaoke_aligned || 0} karaoke aligned</span><span>{job.summary?.unlinked || 0} unlinked</span></div>}</section> : <section className={styles.ready}><div className={styles.mode}><button className={mode === "all" ? styles.selected : ""} onClick={() => setMode("all")}><strong>ENTIRE LIBRARY</strong><small>Fill missing audio, lyrics, and karaoke analysis for every track</small></button><button className={mode === "missing" ? styles.selected : ""} onClick={() => setMode("missing")}><strong>NEW TRACKS ONLY</strong><small>Process the {status?.missing || 0} tracks not yet indexed</small></button></div><button className={styles.start} onClick={start} disabled={busy || !status || (mode === "missing" && status.missing === 0)}>START PROCESSING <b>↗</b></button></section>}
        <section className={styles.queue}><header><span>WAITING IN NAVIDROME</span><b>{status?.missing || 0}</b></header><div>{status?.tracks.length ? status.tracks.map(track => <article key={track.id}><span>{track.title}</span><small>{track.artist || "Unknown artist"}</small><i>{track.album || "Unknown album"}</i></article>) : <p>{busy ? "Scanning the catalog" : "No unprocessed tracks found"}</p>}</div></section>
        {error && <p className={styles.error}>{error}</p>}
      </section>
    </main>
  </AppShell>;
}
