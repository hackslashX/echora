"use client";

import { Clock3, Disc3, ListMusic, MessageSquareText, Pause, Play, RefreshCw, Save, WandSparkles } from "lucide-react";
import LoadingImage from "../media/LoadingImage";
import { useEffect, useState } from "react";
import { usePlayer, type PlayerTrack } from "../player/PlayerProvider";
import AppShell from "../shell/AppShell";
import CopyrightFooter from "../shell/CopyrightFooter";
import { trackTemplate } from "../shell/gridGeometry";
import styles from "./CurateLibrary.module.css";
import TrackReferencePicker, { type ReferenceTrack } from "./TrackReferencePicker";

type Reference = { kind: "track" | "artist" | "album"; name: string };
type Track = { id: string; title: string; artist?: string; album?: string; duration_seconds: number; source_id: string; cover_art?: string; score: number; percentile?: number; position?: number };
type Preview = { tracks: Track[]; references: { positive: Reference[]; negative: Reference[] }; corpus_size: number; familiarity?: { active: boolean; percent: number; familiar_tracks: number; discovery_tracks: number; matched_listens: number } };
type CurationType = "language" | "examples" | "time_of_day";
type Curation = { id: string; name: string; curation_type: CurationType; positive_prompt: string; negative_prompt: string; positive_tracks: ReferenceTrack[]; negative_tracks: ReferenceTrack[]; familiarity_percent: number; period_start?: string; period_end?: string; lookback_days: number; track_limit: number; refresh_mode: "stable" | "fresh"; refresh_enabled: boolean; status: string; last_error?: string; last_refreshed_at?: string; next_refresh_at?: string; tracks: Track[] };

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/analysis${path}`, options);
  const body = response.status === 204 ? null : await response.json();
  if (!response.ok) throw new Error(body?.detail || "The request failed");
  return body as T;
}

export default function CurateLibrary() {
  const { playQueue, track: current, playing, toggle } = usePlayer();
  const [connectionId, setConnectionId] = useState("");
  const [historyConnected, setHistoryConnected] = useState(false);
  const [name, setName] = useState("");
  const [curationType, setCurationType] = useState<CurationType>("language");
  const [positive, setPositive] = useState("");
  const [negative, setNegative] = useState("");
  const [positiveTracks, setPositiveTracks] = useState<ReferenceTrack[]>([]);
  const [negativeTracks, setNegativeTracks] = useState<ReferenceTrack[]>([]);
  const [familiarityPercent, setFamiliarityPercent] = useState(70);
  const [periodStart, setPeriodStart] = useState("18:00");
  const [periodEnd, setPeriodEnd] = useState("23:00");
  const [trackLimit, setTrackLimit] = useState(30);
  const [refreshMode, setRefreshMode] = useState<"stable" | "fresh">("stable");
  const [refreshEnabled, setRefreshEnabled] = useState(true);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [curations, setCurations] = useState<Curation[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function loadCurations() { api<{ curations: Curation[] }>("/library/curations").then(body => setCurations(body.curations)).catch(reason => setError(reason.message)); }
  useEffect(() => { api<{ navidrome_connection_id?: string }>("/auth/me").then(user => setConnectionId(user.navidrome_connection_id || "")); api<{ lastfm: { connected: boolean } }>("/settings").then(body => setHistoryConnected(body.lastfm.connected)).catch(() => {}); loadCurations(); }, []);

  const recipe = { curation_type: curationType, positive_prompt: curationType === "language" ? positive : "", negative_prompt: curationType === "language" ? negative : "", positive_track_ids: curationType === "examples" ? positiveTracks.map(track => track.id) : [], negative_track_ids: curationType === "examples" ? negativeTracks.map(track => track.id) : [], familiarity_percent: familiarityPercent, period_start: curationType === "time_of_day" ? periodStart : null, period_end: curationType === "time_of_day" ? periodEnd : null, lookback_days: 7, track_limit: trackLimit, refresh_mode: refreshMode };
  const hasPositiveEvidence = curationType === "language" ? positive.trim().length > 0 : curationType === "examples" ? positiveTracks.length > 0 : historyConnected && Boolean(periodStart && periodEnd);
  async function generate() {
    setBusy(true); setError("");
    try { setPreview(await api<Preview>("/library/curations/preview", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(recipe) })); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not generate the playlist"); }
    finally { setBusy(false); }
  }
  async function save() {
    if (!name.trim()) { setError("Give the curation a name before saving it"); return; }
    setBusy(true); setError("");
    try {
      await api("/library/curations", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ ...recipe, name, refresh_enabled: refreshEnabled }) });
      await loadCurations();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not save the curation"); }
    finally { setBusy(false); }
  }
  function playerTracks(tracks: Track[]): PlayerTrack[] { return tracks.map(track => ({ id: track.id, title: track.title, artist: track.artist, album: track.album, durationSeconds: track.duration_seconds, coverUrl: track.cover_art && connectionId ? `/analysis/navidrome/connections/${connectionId}/cover/${track.cover_art}` : undefined, streamUrl: `/analysis/navidrome/connections/${connectionId}/stream/${track.source_id}` })); }
  async function refresh(curation: Curation) { setBusy(true); setError(""); try { await api(`/library/curations/${curation.id}/refresh`, { method: "POST" }); loadCurations(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Refresh failed"); } finally { setBusy(false); } }
  async function toggleSchedule(curation: Curation) { try { await api(`/library/curations/${curation.id}`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ refresh_enabled: !curation.refresh_enabled }) }); loadCurations(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not update the schedule"); } }

  const shown = preview?.tracks || [];
  const columns = [0.35, 0.04, 0.61];
  return <AppShell title="Curate" footer={<CopyrightFooter />} breadcrumb flush fullPage grid={{ columns, rows: [1] }}>
    <main className={styles.page} style={{ gridTemplateColumns: trackTemplate(columns, 180), gridTemplateRows: trackTemplate([1], 152) }}>
      <section className={styles.recipe}>
        <header><h1>Build playlists</h1><p>Describe what belongs and what does not. Named tracks, artists, and albums become explicit examples.</p></header>
        <nav className={styles.types} aria-label="Curation type"><button className={curationType === "language" ? styles.activeType : ""} onClick={() => setCurationType("language")}><MessageSquareText /><span>Language</span></button><button className={curationType === "examples" ? styles.activeType : ""} onClick={() => setCurationType("examples")}><ListMusic /><span>Like / not like</span></button><button className={curationType === "time_of_day" ? styles.activeType : ""} onClick={() => setCurationType("time_of_day")}><Clock3 /><span>Time of day</span>{!historyConnected && <small>Needs Last.fm</small>}</button></nav>
        <label><span>Playlist name</span><input value={name} onChange={event => setName(event.target.value)} placeholder="Late-night circuitry" /></label>
        {curationType === "language" && <><label><span>Positive direction</span><textarea value={positive} onChange={event => setPositive(event.target.value)} placeholder="Dreamy electronic music with soft vocals and patient builds" /></label><label><span>Keep out</span><textarea value={negative} onChange={event => setNegative(event.target.value)} placeholder="Avoid aggressive, bright, or hurried music" /></label></>}
        {curationType === "examples" && <><TrackReferencePicker label="Songs like" value={positiveTracks} onChange={setPositiveTracks} /><TrackReferencePicker label="Songs not like" value={negativeTracks} onChange={setNegativeTracks} /></>}
        {curationType === "time_of_day" && <section className={styles.timeScaffold}><header><Clock3 /><div><strong>Recurring listening period</strong><small>Playlist generation uses the previous seven days of Last.fm history.</small></div></header><div><label><span>From</span><input type="time" value={periodStart} onChange={event => setPeriodStart(event.target.value)} /></label><label><span>Until</span><input type="time" value={periodEnd} onChange={event => setPeriodEnd(event.target.value)} /></label></div><p>Overnight periods are supported. Listening periods use the timezone selected in Settings.</p></section>}
        <div className={styles.familiarity}><header><span>Listening mix</span><b>{familiarityPercent}% familiar · {100 - familiarityPercent}% discovery</b></header><input type="range" min="0" max="100" step="5" value={familiarityPercent} onChange={event => setFamiliarityPercent(Number(event.target.value))} aria-label="Familiar and discovery track mix" /><small>{historyConnected ? "Applied using the previous seven days of matched Last.fm listens." : "Inactive until Last.fm listening history is connected. This setting is saved with the playlist."}</small></div>
        <div className={styles.controls}><label><span>Tracks</span><input type="number" min="5" max="200" value={trackLimit} onChange={event => setTrackLimit(Number(event.target.value))} /></label><label><span>Refresh style</span><select value={refreshMode} onChange={event => setRefreshMode(event.target.value as "stable" | "fresh")}><option value="stable">Stable</option><option value="fresh">Fresh</option></select></label></div>
        <button className={styles.schedule} onClick={() => setRefreshEnabled(value => !value)}><Clock3 /><span>Refresh every 6 hours</span><b>{refreshEnabled ? "ON" : "OFF"}</b></button>
        <div className={styles.actions}><button onClick={generate} disabled={busy || !hasPositiveEvidence}><WandSparkles />{busy ? "WORKING" : "PREVIEW"}</button><button onClick={save} disabled={busy || !hasPositiveEvidence}><Save />SAVE + SYNC</button></div>
        {error && <p className={styles.error}>{error}</p>}
        <section className={styles.saved}><h2>Saved curations</h2>{curations.length ? curations.map(curation => <article key={curation.id}><button className={styles.savedMain} onClick={() => { setName(curation.name); setCurationType(curation.curation_type || "language"); setPositive(curation.positive_prompt); setNegative(curation.negative_prompt); setPositiveTracks(curation.positive_tracks || []); setNegativeTracks(curation.negative_tracks || []); setFamiliarityPercent(curation.familiarity_percent ?? 70); setPeriodStart(curation.period_start || "18:00"); setPeriodEnd(curation.period_end || "23:00"); setTrackLimit(curation.track_limit); setRefreshMode(curation.refresh_mode); setRefreshEnabled(curation.refresh_enabled); setPreview({ tracks: curation.tracks, references: { positive: [], negative: [] }, corpus_size: 0 }); }}><strong>{curation.name}</strong><small>{curation.tracks.length} tracks · {curation.status}</small></button><button title="Refresh now" onClick={() => refresh(curation)}><RefreshCw /></button><button title="Toggle schedule" className={curation.refresh_enabled ? styles.enabled : ""} onClick={() => toggleSchedule(curation)}><Clock3 /></button></article>) : <p>No saved curations yet.</p>}</section>
      </section>
      <section className={styles.results}>
        <header><h2>{name || "Playlist preview"}</h2><strong>{shown.length}</strong></header>
        {preview?.references && <div className={styles.references}>{(["positive", "negative"] as const).map(kind => preview.references[kind].map(reference => <span className={kind === "negative" ? styles.negative : ""} key={`${kind}-${reference.kind}-${reference.name}`}>{reference.kind} · {reference.name}</span>))}</div>}
        <div className={styles.trackList}>{shown.length ? shown.map((track, index) => <article key={track.id}><b>{String(index + 1).padStart(2, "0")}</b><div className={styles.art}>{track.cover_art && connectionId ? <LoadingImage sizes="46px" src={`/analysis/navidrome/connections/${connectionId}/cover/${track.cover_art}`} alt="" /> : <Disc3 />}</div><div><strong>{track.title}</strong><small>{track.artist || "Unknown artist"} · {track.album || "Unknown album"}</small></div><span>{track.percentile == null ? track.score.toFixed(2) : `TOP ${Math.max(1, Math.round((1 - track.percentile) * 100))}%`}</span><button onClick={() => current?.id === track.id ? toggle() : playQueue(playerTracks(shown), index)} aria-label={`Play ${track.title}`}>{current?.id === track.id && playing ? <Pause /> : <Play />}</button></article>) : <p>Write a recipe and preview it. Resolved references and ranked tracks will appear here.</p>}</div>
        {shown.length > 0 && <footer><button onClick={() => playQueue(playerTracks(shown), 0)}><Play /> PLAY PREVIEW</button><span>{preview?.familiarity?.active ? `${preview.familiarity.familiar_tracks} familiar · ${preview.familiarity.discovery_tracks} discovery · shuffled` : "45% MuQ-MuLan sound · 55% BGE-M3 lyrics"}</span></footer>}
      </section>
    </main>
  </AppShell>;
}
