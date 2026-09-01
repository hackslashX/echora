"use client";

import LoadingImage from "./media/LoadingImage";
import { coverArtUrl } from "./media/coverArt";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";
import AppFooter from "./shell/AppFooter";
import AppShell from "./shell/AppShell";
import EdgeLines from "./shell/EdgeLines";
import StepNavigation from "./onboarding/StepNavigation";

type Credentials = { url: string; username: string; password: string };
type Track = { id: string; title: string; artist?: string; album?: string; duration: number; genre?: string; cover_art?: string };
type Job = { job_id: string; status: "queued" | "running" | "complete" | "failed"; phase: string; message?: string; completed: number; total: number; unit?: "models" | "tracks"; error?: string; track?: Pick<Track, "id" | "title" | "artist">; summary?: Record<string, number> };

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/analysis${path}`, options);
  const body = await response.text();
  let payload: Record<string, unknown>;
  try { payload = body ? JSON.parse(body) : {}; }
  catch { throw new Error(response.ok ? "The server returned an invalid response" : `The analysis service failed (${response.status})`); }
  if (!response.ok) throw new Error(String(payload.detail || payload.error || "The request failed"));
  return payload as T;
}

const formatDuration = (seconds: number) => `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, "0")}`;

export default function SetupWizard({ initialStep = 0 }: { initialStep?: number }) {
  const router = useRouter();
  const [step, setStep] = useState(initialStep);
  const [credentials, setCredentials] = useState<Credentials>({ url: "http://host.docker.internal:4533", username: "", password: "" });
  const [limit, setLimit] = useState(100);
  const [tracks, setTracks] = useState<Track[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [server, setServer] = useState("");
  const [connectionId, setConnectionId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [job, setJob] = useState<Job | null>(null);

  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    const timer = window.setTimeout(async () => {
      try { setJob(await api<Job>(`/jobs/${job.job_id}`)); }
      catch (reason) { setError(reason instanceof Error ? reason.message : "Could not read job progress"); }
    }, 1200);
    return () => window.clearTimeout(timer);
  }, [job]);

  const chosen = useMemo(() => tracks.filter(track => selected.has(track.id)), [tracks, selected]);

  function navigate(nextStep: number) {
    if (nextStep > 0 && tracks.length === 0) nextStep = 0;
    setStep(nextStep);
    window.history.pushState({}, "", ["/connect", "/select", "/process"][nextStep]);
  }

  useEffect(() => {
    const onHistory = () => setStep(Math.max(0, ["/connect", "/select", "/process"].indexOf(window.location.pathname)));
    window.addEventListener("popstate", onHistory);
    return () => window.removeEventListener("popstate", onHistory);
  }, []);

  async function discover(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const result = await api<{ connection_id: string; server: { version: string }; tracks: Track[] }>("/navidrome/discover", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ ...credentials, limit }) });
      setTracks(result.tracks); setSelected(new Set(result.tracks.map(track => track.id))); setServer(result.server.version); setConnectionId(result.connection_id); navigate(1);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Connection failed"); }
    finally { setBusy(false); }
  }

  function toggle(id: string) {
    setSelected(current => { const next = new Set(current); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  }

  async function start() {
    setBusy(true); setError("");
    try {
      const result = await api<{ job_id: string; status: "queued" }>("/ingest/navidrome", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ ...credentials, track_ids: chosen.map(track => track.id) }) });
      setJob({ ...result, phase: "queued", completed: 0, total: chosen.length }); navigate(2);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not start processing"); }
    finally { setBusy(false); }
  }

  const percent = job?.total ? Math.round(job.completed / job.total * 100) : 0;

  async function finishOnboarding() {
    setError("");
    try {
      const response = await fetch("/analysis/users/me/preferences/onboarding", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ complete: true, connection_id: connectionId || null }) });
      if (!response.ok) throw new Error("Could not save onboarding preferences");
      window.dispatchEvent(new CustomEvent("echora:user-update", { detail: { onboarding_complete: true } }));
      router.push("/home");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not finish onboarding"); }
  }

  const footer = <AppFooter pinned marker={<>0{step + 1} <span>/ 03</span></>}><StepNavigation step={step} navigate={navigate} /></AppFooter>;

  return <AppShell title="Getting started" footer={footer} onboarding>

        {step === 0 && <form className="wizard-card connect-card" onSubmit={discover}>
          <EdgeLines />
          <h1>Meet your<br />music library.</h1>
          <div className="fields">
            <label className="wide"><span>Server URL</span><input required type="url" value={credentials.url} onChange={event => setCredentials({ ...credentials, url: event.target.value })} /></label>
            <label><span>Username</span><input required autoComplete="username" value={credentials.username} onChange={event => setCredentials({ ...credentials, username: event.target.value })} /></label>
            <label><span>Password</span><input required type="password" autoComplete="current-password" value={credentials.password} onChange={event => setCredentials({ ...credentials, password: event.target.value })} /></label>
          </div>
          <div className="sample-control"><span>Sample</span><input type="range" min="10" max="200" step="10" value={limit} onChange={event => setLimit(Number(event.target.value))} /><output>{limit}</output></div>
          {error && <p className="error">{error}</p>}
          <button className="primary" disabled={busy}>{busy ? "Connecting…" : <>Find my music <b>↗</b></>}</button>
        </form>}

        {step === 1 && <div className="wizard-card review-card">
          <EdgeLines />
          <div className="review-heading"><div><h1>Choose tracks<br />to analyze.</h1><p className="connection-meta"><span>Navidrome {server}</span><b>Connected</b></p></div><div className="found-count"><strong>{tracks.length}</strong><span>tracks found</span></div></div>
          <div className="table-tools"><button onClick={() => setSelected(selected.size === tracks.length ? new Set() : new Set(tracks.map(track => track.id)))}>{selected.size === tracks.length ? "Clear selection" : "Select all"}</button><span>{selected.size} selected</span></div>
          <div className="song-list">{tracks.map((track, index) => <label key={track.id} className={selected.has(track.id) ? "song chosen" : "song"}>
            <input type="checkbox" checked={selected.has(track.id)} onChange={() => toggle(track.id)} />
            <span className={`art art-${index % 5}`}>{track.cover_art && connectionId ? <LoadingImage sizes="42px" src={coverArtUrl(connectionId, track.cover_art, 84)} alt="" /> : <i />}</span>
            <span className="song-name"><strong>{track.title}</strong><small>{track.artist || "Unknown artist"}</small></span>
            <span className="song-album">{track.album || "Unknown album"}</span><time>{formatDuration(track.duration)}</time>
          </label>)}</div>
          {error && <p className="error">{error}</p>}
          <div className="review-action"><button className="primary" onClick={start} disabled={busy || !selected.size}>Process {selected.size} tracks <b>↗</b></button></div>
        </div>}

        {step === 2 && <div className="wizard-card processing-card">
          <EdgeLines />
          <h1>{job?.status === "complete" ? <>Analysis<br />complete.</> : <>Build music<br />embeddings.</>}</h1>
          <div className="progress-summary"><div><span className="phase">{job?.status === "complete" ? "Complete" : job?.phase || "Queued"}</span><strong>{job?.message || "Waiting for worker"}</strong><span>{job?.track ? `${job.track.artist || "Unknown artist"} — ${job.track.title}` : `${job?.completed || 0} of ${job?.total || chosen.length} ${job?.unit || "tracks"}`}</span></div><b>{percent}%</b></div>
          <div className="meter"><i style={{ width: `${job?.phase === "models" ? 5 : percent}%` }} /></div>
          <div className="process-stages">
            {[{ key: "models", label: "Load models" }, { key: "processing", label: "Process tracks" }, { key: "finalizing", label: "Save index" }].map((stage, index) => {
              const order = ["models", "processing", "finalizing", "complete"];
              const current = order.indexOf(job?.phase || "models");
              return <span key={stage.key} className={current > index ? "done" : current === index ? "active" : ""}>{current > index ? "✓" : `0${index + 1}`} <b>{stage.label}</b></span>;
            })}
          </div>
          <div className="process-count">{job?.completed || 0} / {job?.total || chosen.length} tracks</div>
          {job?.status === "failed" && <p className="error">{job.error}</p>}
          {job?.status === "complete" && <><div className="result-numbers"><div><strong>{job.summary?.inserted || 0}</strong><span>new</span></div><div><strong>{job.summary?.already_linked || 0}</strong><span>reused</span></div><div><strong>{job.summary?.failed || 0}</strong><span>failed</span></div></div><button className="primary enter-button" onClick={finishOnboarding}>Enter Echora <b>→</b></button></>}
        </div>}
  </AppShell>;
}
