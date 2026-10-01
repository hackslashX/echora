"use client";

import { toast } from "sonner";
import { useDurableJob } from "../jobs/useDurableJob";
import { jobPresentation } from "../jobs/durableJobs";
import LoadingImage from "../media/LoadingImage";
import { coverArtUrl } from "../media/coverArt";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";
import AppFooter from "../shell/AppFooter";
import AppShell from "../shell/AppShell";
import { Button } from "../ui/button";
import { Notice } from "../ui/notice";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "../ui/card";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Checkbox } from "../ui/checkbox";
import { Table, TableHeader, TableHead, TableBody, TableRow, TableCell } from "../ui/table";
import StepNavigation from "./StepNavigation";
import { PageHeader } from "../layout/page-header";
import styles from "./SetupWizard.module.css";

type Credentials = { url: string; username: string; password: string };
type Track = { id: string; title: string; artist?: string; album?: string; duration: number; genre?: string; cover_art?: string };

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
  const [requestedStep, setStep] = useState(initialStep);
  const [credentials, setCredentials] = useState<Credentials>({ url: "http://host.docker.internal:4533", username: "", password: "" });
  const [limit, setLimit] = useState(100);
  const [tracks, setTracks] = useState<Track[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [server, setServer] = useState("");
  const [connectionId, setConnectionId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const { job, active, terminal, error: jobError, loading: jobLoading, track, dismiss } = useDurableJob(connectionId);

  useEffect(() => {
    const controller = new AbortController();
    api<{ navidrome_connection_id?: string }>("/auth/me", { signal: controller.signal }).then(user => { if (!controller.signal.aborted) setConnectionId(user.navidrome_connection_id || ""); }).catch(reason => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, []);
  const step = job ? 2 : requestedStep;

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
    } catch (reason) { toast.error("Connection failed", { description: reason instanceof Error && reason.message !== "Connection failed" ? reason.message : undefined }); }
    finally { setBusy(false); }
  }

  function toggle(id: string) {
    setSelected(current => { const next = new Set(current); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  }

  async function start() {
    setBusy(true); setError("");
    try {
      const result = await api<{ job_id: string; status: "queued" }>("/ingest/navidrome", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ ...credentials, track_ids: chosen.map(track => track.id) }) });
      track(result.job_id); navigate(2);
    } catch (reason) { toast.error("Could not start processing", { description: reason instanceof Error && reason.message !== "Could not start processing" ? reason.message : undefined }); }
    finally { setBusy(false); }
  }

  const presentation = jobPresentation(job);
  const { percent } = presentation;

  async function finishOnboarding() {
    setError("");
    try {
      const response = await fetch("/analysis/users/me/preferences/onboarding", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ complete: true, connection_id: connectionId || null }) });
      if (!response.ok) throw new Error("Could not save onboarding preferences");
      window.dispatchEvent(new CustomEvent("echora:user-update", { detail: { onboarding_complete: true } }));
      router.push("/home");
    } catch (reason) { toast.error("Could not finish onboarding", { description: reason instanceof Error && reason.message !== "Could not finish onboarding" ? reason.message : undefined }); }
  }

  const footer = <AppFooter pinned marker={<>0{step + 1} <span>/ 03</span></>}><StepNavigation step={step} navigate={navigate} /></AppFooter>;

  return <AppShell title="Getting started" footer={footer} onboarding>
    <section className={styles.workspace}>
      {step === 0 && <section className={styles.step}>
        <PageHeader title="Connect your music" description="Use your Navidrome server to bring your own library into Echora." />
        <div className={`${styles.content} ${styles.connect}`}><form id="connect-library" onSubmit={discover} className="space-y-6">
          <div className="space-y-2"><Label htmlFor="server-url">Server URL</Label><Input id="server-url" required type="url" value={credentials.url} onChange={event => setCredentials({ ...credentials, url: event.target.value })} /></div>
          <div className="grid gap-6 sm:grid-cols-2"><div className="space-y-2"><Label htmlFor="username">Username</Label><Input id="username" required autoComplete="username" value={credentials.username} onChange={event => setCredentials({ ...credentials, username: event.target.value })} /></div><div className="space-y-2"><Label htmlFor="password">Password</Label><Input id="password" required type="password" autoComplete="current-password" value={credentials.password} onChange={event => setCredentials({ ...credentials, password: event.target.value })} /></div></div>
          <div className="max-w-xs space-y-2"><Label htmlFor="sample-limit">Tracks to sample</Label><Input id="sample-limit" required type="number" min={10} max={200} step={10} value={limit} onChange={event => setLimit(Number(event.target.value))} /><p className="text-sm text-muted-foreground">Start with 10–200 tracks. Choose which to analyze next.</p></div>
          {error && <Notice tone="error">{error}</Notice>}
        </form><div className="mt-6"><Button form="connect-library" type="submit" loading={busy}>{busy ? "Connecting…" : "Find my music"}</Button></div></div>
      </section>}
      {step === 1 && <section className={styles.step}>
        <PageHeader title="Choose tracks to analyze" description={`Navidrome ${server} connected • ${tracks.length} tracks found`} actions={<Button onClick={start} loading={busy} disabled={jobLoading || active || !!jobError || !selected.size}>{busy ? "Starting…" : `Process ${selected.size} tracks`}</Button>} />
        <div className={`${styles.content} space-y-6`}>
        <div className="flex items-center justify-between border border-border bg-surface/60 px-2 py-1.5"><Button variant="ghost" onClick={() => setSelected(selected.size === tracks.length ? new Set() : new Set(tracks.map(track => track.id)))}>{selected.size === tracks.length ? "Clear selection" : "Select all"}</Button><span className="text-sm text-muted-foreground">{selected.size} selected</span></div>
        <div className="border border-border"><Table><TableHeader><TableRow><TableHead className="w-12">Select</TableHead><TableHead>Track</TableHead><TableHead className="hidden md:table-cell">Album</TableHead><TableHead className="text-right">Time</TableHead></TableRow></TableHeader><TableBody>{tracks.map(track => <TableRow key={track.id} data-state={selected.has(track.id) ? "selected" : undefined}><TableCell><Checkbox aria-label={`Select ${track.title}`} checked={selected.has(track.id)} onCheckedChange={() => toggle(track.id)} /></TableCell><TableCell><div className="flex items-center gap-3"><div className="relative size-10 shrink-0 overflow-hidden rounded-none bg-raised">{track.cover_art && connectionId && <LoadingImage sizes="40px" src={coverArtUrl(connectionId, track.cover_art, 84)} alt="" />}</div><div><div className="font-medium">{track.title}</div><div className="text-sm text-muted-foreground">{track.artist || "Unknown artist"}</div></div></div></TableCell><TableCell className="hidden text-muted-foreground md:table-cell">{track.album || "Unknown album"}</TableCell><TableCell className="text-right text-muted-foreground">{formatDuration(track.duration)}</TableCell></TableRow>)}</TableBody></Table></div>
        {!tracks.length && <p className="text-muted-foreground">Connect your server to discover tracks. <Button variant="link" onClick={() => navigate(0)}>Connect server</Button></p>}
        {error && <Notice tone="error">{error}</Notice>}
        </div>
      </section>}
      {step === 2 && <section className={styles.step} aria-live="polite">
        <PageHeader title={job?.status === "complete" ? "Your library is ready" : "Analyzing your music"} description={presentation.message} />
        <div className={`${styles.content} space-y-8`}>
        <Card className="max-w-3xl"><CardHeader><CardTitle className="flex justify-between gap-4"><span>{job?.status === "complete" ? "Complete" : terminal ? job?.status : job?.phase || "Queued"}</span>{presentation.showPercent && <span>{percent}%</span>}</CardTitle><CardDescription>{job?.track ? `${job.track.artist || "Unknown artist"} — ${job.track.title}` : presentation.detail}</CardDescription></CardHeader><CardContent className="space-y-6">
          {presentation.showPercent && <progress aria-label="Analysis progress" max={100} value={job?.phase === "models" ? 5 : percent} className="h-1.5 w-full accent-[var(--accent)]" />}
          <ol className="grid gap-4 sm:grid-cols-3">{[{ key: "models", label: "Load models" }, { key: "processing", label: "Process tracks" }, { key: "finalizing", label: "Save index" }].map((stage, index) => { const current = ["models", "processing", "finalizing", "complete"].indexOf(job?.phase || "models"); return <li key={stage.key} aria-current={current === index ? "step" : undefined} className={current >= index ? "text-primary" : "text-subtle-foreground"}><span className="mr-2">{current > index ? "✓" : index + 1}</span>{stage.label}</li>; })}</ol>
          <p className="text-sm text-muted-foreground">{presentation.detail}</p>
          {presentation.summary.length > 0 && <ul className="space-y-2 text-sm">{presentation.summary.map(item => <li key={item}>{item}</li>)}</ul>}
        </CardContent></Card>
        {(error || job?.error) && <Notice tone="error">{error || job?.error}</Notice>}
        <div className="flex flex-wrap gap-3">{(job?.status === "complete" || job?.status === "partial") && <Button onClick={finishOnboarding}>Enter Echora</Button>}{terminal && <Button variant="outline" onClick={() => { dismiss(); navigate(tracks.length ? 1 : 0); }}>Dismiss / start again</Button>}</div>
        </div>
      </section>}
    </section>
  </AppShell>;
}
