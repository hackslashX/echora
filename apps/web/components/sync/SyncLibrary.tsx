"use client";

import { Check, CircleCheck, Database, RefreshCw, Server, Waves } from "lucide-react";
import { useEffect, useState } from "react";
import AppShell from "../shell/AppShell";
import CopyrightFooter from "../shell/CopyrightFooter";
import { trackTemplate } from "../shell/gridGeometry";
import MobilePivots from "../shell/MobilePivots";
import { useDurableJob } from "../jobs/useDurableJob";
import { jobPresentation } from "../jobs/durableJobs";
import BatchStatusList from "../jobs/BatchStatusList";
import styles from "./SyncLibrary.module.css";

type Track = { id: string; title: string; artist?: string; album?: string };
type Status = { server: string; total: number; processed: number; missing: number; tracks: Track[] };

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/analysis${path}`, options);
  const body = await response.json().catch(() => null);
  if (!response.ok || !body) throw new Error(body?.detail || `The request failed (${response.status})`);
  return body as T;
}

export default function SyncLibrary() {
  const [connectionId, setConnectionId] = useState("");
  const [status, setStatus] = useState<Status | null>(null);
  const { job, active, terminal, error: jobError, loading: jobLoading, track, dismiss } = useDurableJob(connectionId);
  const [mode, setMode] = useState<"all" | "missing">("all");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [mobilePane, setMobilePane] = useState<"status" | "method">("status");

  function scan(connection: string) {
    setBusy(true); setError("");
    api<Status>(`/navidrome/connections/${connection}/sync/status`).then(setStatus).catch(reason => setError(reason.message)).finally(() => setBusy(false));
  }

  useEffect(() => {
    fetch("/analysis/auth/me").then(response => response.json()).then(user => {
      const connection = user.navidrome_connection_id || ""; setConnectionId(connection);
      if (connection) scan(connection); else { setError("No Navidrome connection is configured"); setBusy(false); }

    }).catch(() => { setError("Could not load your connection"); setBusy(false); });
  }, []);

  useEffect(() => {
    if (!terminal || !connectionId) return;
    const timer = window.setTimeout(() => scan(connectionId), 400);
    return () => window.clearTimeout(timer);
  }, [connectionId, terminal]);

  async function start() {
    if (!connectionId) return; setBusy(true); setError("");
    try {
      const result = await api<{ job_id: string; status: string; existing: boolean }>(`/navidrome/connections/${connectionId}/sync`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ mode }) });
      track(result.job_id);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not start synchronization"); }
    finally { setBusy(false); }
  }

  const indeterminatePhases = new Set(["queued", "scanning", "starting", "planning", "models"]);
  const indeterminate = Boolean(active && (job?.unit === "models" || indeterminatePhases.has(job?.phase || "")));
  const presentation = jobPresentation(job);
  const { percent } = presentation;
  const progressDetail = job?.unit === "models"
    ? `${job.completed} of ${job.total} models ready`
    : indeterminate
      ? "This setup step does not report track progress"
      : presentation.detail;
  const columns = [0.32, 0.04, 0.64];
  const rows = [1];
  return <AppShell title="Sync" footer={<CopyrightFooter />} breadcrumb flush fullPage grid={{ columns, rows }}>
    <main className={styles.page} style={{ gridTemplateColumns: trackTemplate(columns, 160), gridTemplateRows: trackTemplate(rows, 88) }}>
      <MobilePivots label="Sync sections" active={mobilePane} onChange={setMobilePane} items={[{ key: "status", label: "status" }, { key: "method", label: "how it works" }]} />
      <section className={`${styles.intro} ${mobilePane === "method" ? styles.mobileActive : ""}`}> <h1>Sync,<br /><em>step by step.</em></h1><p>Sync reads your server without changing its library. Echora keeps existing analysis and processes only the work each track still needs.</p><ol className={styles.steps}><li><b>1</b><div><strong>Read the catalog</strong><small>Load track IDs, metadata, artwork references, and the current library count from Navidrome.</small></div></li><li><b>2</b><div><strong>Resolve track identity</strong><small>Stream the source audio and use its SHA-256 content hash to link duplicates without merging recordings.</small></div></li><li><b>3</b><div><strong>Analyze missing representations</strong><div className={styles.models}><p><b>MuQ-MuLan</b><span>Maps musical meaning, style, mood, vocals, and instrumentation.</span></p><p><b>MERT</b><span>Measures acoustic structure, timbre, rhythm, pitch, and production.</span></p><p><b>BGE-M3</b><span>Maps lyric language, themes, imagery, and narrative.</span></p><p><b>Essentia</b><span>Identifies instrumental music and female or male lead vocals.</span></p><p><b>Demucs + MELODIA</b><span>Extracts full-mix, vocal, and accompaniment contours for hum search.</span></p><p><b>Echora aligner</b><span>Aligns time-synced lyrics to syllable-level karaoke timing.</span></p></div></div></li><li><b>4</b><div><strong>Commit the results</strong><small>Store embeddings, karaoke lyrics, and provenance, then make the tracks available to Browse, Galaxy, concepts, journeys, and the player.</small></div></li></ol><div className={styles.server}><Server /><div><small>Connected server</small><strong>{status?.server || "Reading connection"}</strong></div></div></section>
      <section className={`${styles.workspace} ${mobilePane === "status" ? styles.mobileActive : ""}`}>
        <header><div><h2>{active ? "Processing library" : busy ? "Scanning Navidrome" : "Library scan complete"}</h2></div><button onClick={() => connectionId && scan(connectionId)} disabled={busy || !!active}><RefreshCw /> RESCAN</button></header>
        <div className={styles.metrics}><div><Database /><strong>{status?.total ?? "—"}</strong><span>Navidrome tracks</span></div><div><Check /><strong>{status?.processed ?? "—"}</strong><span>Already indexed</span></div><div><Waves /><strong>{status?.missing ?? "—"}</strong><span>New tracks</span></div></div>
        {job ? <section className={`${styles.progress} ${indeterminate ? styles.indeterminate : ""}`}><div><span>{job?.phase?.toUpperCase()}</span><strong>{presentation.message}</strong><small>{progressDetail}</small></div><div className={styles.progressActions}>{terminal ? <button className={styles.dismiss} onClick={dismiss} aria-label="Dismiss sync results">Dismiss</button> : !indeterminate && presentation.showPercent && <b>{percent}%</b>}</div>{(active || job.status === "complete") && <i role="progressbar" aria-label={indeterminate ? "Preparing analysis" : "Library sync progress"} aria-valuemin={indeterminate ? undefined : 0} aria-valuemax={indeterminate ? undefined : 100} aria-valuenow={indeterminate ? undefined : percent}><u style={indeterminate ? undefined : { width: `${percent}%` }} /></i>}{job?.error && <p>{job.error}</p>}{terminal && presentation.summary.length > 0 && <div className={styles.summary}>{presentation.summary.map(item => <span key={item}>{item}</span>)}</div>}</section> : <section className={styles.ready}><div className={styles.mode}><button className={mode === "all" ? styles.selected : ""} onClick={() => setMode("all")}><strong>ENTIRE LIBRARY</strong><small>Fill missing analysis for existing and new tracks</small></button><button className={mode === "missing" ? styles.selected : ""} onClick={() => setMode("missing")}><strong>NEW TRACKS ONLY</strong><small>Process the {status?.missing || 0} tracks not yet indexed</small></button></div><button className={styles.start} onClick={start} disabled={busy || jobLoading || !!jobError || !status || (mode === "missing" && status.missing === 0)}>START PROCESSING <b>↗</b></button></section>}
        <section className={styles.queue}><header><span>{job ? "SYNC DETAILS" : "WAITING IN NAVIDROME"}</span><b>{status?.missing || 0} new tracks</b></header><div>{job && <BatchStatusList key={job.job_id || job.id} jobId={job.job_id || job.id!} active={active} />}{status?.tracks.length ? status.tracks.map(track => <article key={track.id}><span>{track.title}</span><small>{track.artist || "Unknown artist"}</small><i>{track.album || "Unknown album"}</i></article>) : <div className={styles.queueEmpty}>{busy ? <RefreshCw className={styles.scanningIcon} aria-hidden="true" /> : <CircleCheck aria-hidden="true" />}<p>{busy ? "Scanning the catalog" : "No unprocessed tracks found"}</p></div>}</div></section>
        {(error || jobError) && <p role="alert" className={styles.error}>{error || jobError}</p>}
      </section>
    </main>
  </AppShell>;
}
