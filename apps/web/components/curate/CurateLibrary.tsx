"use client";

import { ArrowLeft, Clock3, Disc3, ListMusic, MessageSquareText, Pause, Play, RefreshCw, Save, Trash2, WandSparkles, X } from "lucide-react";
import LoadingImage from "../media/LoadingImage";
import { useEffect, useState } from "react";
import { usePlayer, type PlayerTrack } from "../player/PlayerProvider";
import AppShell from "../shell/AppShell";
import CopyrightFooter from "../shell/CopyrightFooter";
import { trackTemplate } from "../shell/gridGeometry";
import styles from "./CurateLibrary.module.css";
import Alert from "../ui/Alert";
import TagInput, { type Tag } from "./TagInput";
import TrackReferencePicker, { type ReferenceTrack } from "./TrackReferencePicker";

type Reference = { kind: "track" | "artist" | "album"; name: string };
type Track = { id: string; title: string; artist?: string; album?: string; duration_seconds: number; source_id: string; cover_art?: string; score: number; percentile?: number; position?: number; evidence?: { selection_pool?: "familiar" | "discovery"; listen_count?: number } };
type Familiarity = { active: boolean; percent: number; familiar_tracks: number; discovery_tracks: number; matched_listens: number };
type Preview = { tracks: Track[]; references: { positive: Reference[]; negative: Reference[] }; corpus_size: number; weights?: { semantic: number; lyrics: number }; familiarity?: Familiarity };
type RevisionRecipe = { references?: { positive: Reference[]; negative: Reference[] }; weights?: { semantic: number; lyrics: number }; familiarity?: Familiarity };
type CurationType = "language" | "examples" | "time_of_day";
type Curation = { id: string; name: string; curation_type: CurationType; positive_prompt: string; negative_prompt: string; sound_prompts?: string[]; themes_prompts?: string[]; sound_negative_prompts?: string[]; themes_negative_prompts?: string[]; sound_weight?: number; positive_tracks: ReferenceTrack[]; negative_tracks: ReferenceTrack[]; familiarity_percent: number; period_start?: string; period_end?: string; lookback_days: number; track_limit: number; refresh_mode: "stable" | "fresh"; refresh_enabled: boolean; status: string; last_error?: string; last_refreshed_at?: string; next_refresh_at?: string; recipe?: RevisionRecipe; tracks: Track[] };

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/analysis${path}`, options);
  const text = response.status === 204 ? "" : await response.text();
  let body: { detail?: string } | null = null;
  if (text) {
    try { body = JSON.parse(text) as { detail?: string }; }
    catch { body = null; }
  }
  if (!response.ok) throw new Error(body?.detail || text || `The request failed (${response.status})`);
  return (body ?? null) as T;
}

export default function CurateLibrary() {
  const { playQueue, track: current, playing, toggle } = usePlayer();
  const [connectionId, setConnectionId] = useState("");
  const [historyConnected, setHistoryConnected] = useState(false);
  const [name, setName] = useState("");
  const [curationType, setCurationType] = useState<CurationType>("language");
  const [positive, setPositive] = useState("");
  const [negative, setNegative] = useState("");
  const [soundTags, setSoundTags] = useState<Tag[]>([]);
  const [themeTags, setThemeTags] = useState<Tag[]>([]);
  const [soundWeight, setSoundWeight] = useState(50);
  const [positiveTracks, setPositiveTracks] = useState<ReferenceTrack[]>([]);
  const [negativeTracks, setNegativeTracks] = useState<ReferenceTrack[]>([]);
  const [familiarityPercent, setFamiliarityPercent] = useState(70);
  const [periodStart, setPeriodStart] = useState("18:00");
  const [periodEnd, setPeriodEnd] = useState("23:00");
  const [trackLimit, setTrackLimit] = useState(30);
  const [refreshMode, setRefreshMode] = useState<"stable" | "fresh">("stable");
  const [refreshEnabled, setRefreshEnabled] = useState(true);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [detailKind, setDetailKind] = useState<"preview" | "saved" | null>(null);
  const [mobilePane, setMobilePane] = useState<"recipe" | "playlists">("recipe");
  const [curations, setCurations] = useState<Curation[]>([]);
  const [busyAction, setBusyAction] = useState<"preview" | "save" | "refresh" | "delete" | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Curation | null>(null);
  const [error, setError] = useState("");
  const busy = busyAction !== null;

  function loadCurations() { return api<{ curations: Curation[] }>("/library/curations").then(body => setCurations(body.curations)).catch(reason => setError(reason.message)); }
  useEffect(() => { api<{ navidrome_connection_id?: string }>("/auth/me").then(user => setConnectionId(user.navidrome_connection_id || "")); api<{ lastfm: { connected: boolean } }>("/settings").then(body => setHistoryConnected(body.lastfm.connected)).catch(() => {}); loadCurations(); }, []);

  const split = (tags: Tag[]) => ({
    positive: tags.filter(tag => !tag.negative).map(tag => tag.label),
    negative: tags.filter(tag => tag.negative).map(tag => tag.label),
  });
  const sound = split(soundTags);
  const themes = split(themeTags);
  const legacy = curationType === "language" && !sound.positive.length && !themes.positive.length && !sound.negative.length && !themes.negative.length;
  const recipe = { curation_type: curationType, positive_prompt: legacy ? positive : "", negative_prompt: curationType === "language" ? negative : "", sound_prompts: curationType === "language" ? sound.positive : [], themes_prompts: curationType === "language" ? themes.positive : [], sound_negative_prompts: curationType === "language" ? sound.negative : [], themes_negative_prompts: curationType === "language" ? themes.negative : [], sound_weight: soundWeight, positive_track_ids: curationType === "examples" ? positiveTracks.map(track => track.id) : [], negative_track_ids: curationType === "examples" ? negativeTracks.map(track => track.id) : [], familiarity_percent: familiarityPercent, period_start: curationType === "time_of_day" ? periodStart : null, period_end: curationType === "time_of_day" ? periodEnd : null, lookback_days: 7, track_limit: trackLimit, refresh_mode: refreshMode };
  const hasPositiveEvidence = curationType === "language" ? Boolean(sound.positive.length || themes.positive.length || positive.trim()) : curationType === "examples" ? positiveTracks.length > 0 : historyConnected && Boolean(periodStart && periodEnd);
  async function generate() {
    setBusyAction("preview"); setError("");
    try {
      setPreview(await api<Preview>("/library/curations/preview", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(recipe) }));
      setDetailKind("preview"); setMobilePane("playlists");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not generate the playlist"); }
    finally { setBusyAction(null); }
  }
  async function save() {
    if (!name.trim()) { setError("Give the curation a name before saving it"); return; }
    setBusyAction("save"); setError("");
    try {
      await api("/library/curations", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ ...recipe, name, refresh_enabled: refreshEnabled }) });
      await loadCurations();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not save the curation"); }
    finally { setBusyAction(null); }
  }
  function playerTracks(tracks: Track[]): PlayerTrack[] { return tracks.map(track => ({ id: track.id, title: track.title, artist: track.artist, album: track.album, durationSeconds: track.duration_seconds, coverUrl: track.cover_art && connectionId ? `/analysis/navidrome/connections/${connectionId}/cover/${track.cover_art}` : undefined, streamUrl: `/analysis/navidrome/connections/${connectionId}/stream/${track.source_id}` })); }
  async function refresh(curation: Curation) {
    setBusyAction("refresh"); setError("");
    setCurations(items => items.map(item => item.id === curation.id ? { ...item, status: "refreshing", last_error: undefined } : item));
    try { await api(`/library/curations/${curation.id}/refresh`, { method: "POST" }); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Refresh failed"); }
    finally { loadCurations(); setBusyAction(null); }
  }
  async function toggleSchedule(curation: Curation) { try { await api(`/library/curations/${curation.id}`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ refresh_enabled: !curation.refresh_enabled }) }); loadCurations(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not update the schedule"); } }
  async function removeCuration(deleteNavidrome: boolean) {
    if (!deleteTarget) return;
    setBusyAction("delete"); setError("");
    try {
      await api(`/library/curations/${deleteTarget.id}?delete_navidrome=${deleteNavidrome}`, { method: "DELETE" });
      setDeleteTarget(null);
      await loadCurations();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not delete the curation"); }
    finally { setBusyAction(null); }
  }
  function openCuration(curation: Curation) {
    setName(curation.name); setCurationType(curation.curation_type || "language");
    setPositive(curation.positive_prompt); setNegative(curation.negative_prompt);
    setSoundTags((curation.sound_prompts || []).map(label => ({ label, negative: false })).concat((curation.sound_negative_prompts || []).map(label => ({ label, negative: true }))));
    setThemeTags((curation.themes_prompts || []).map(label => ({ label, negative: false })).concat((curation.themes_negative_prompts || []).map(label => ({ label, negative: true }))));
    setSoundWeight(curation.sound_weight ?? 50); setPositiveTracks(curation.positive_tracks || []); setNegativeTracks(curation.negative_tracks || []);
    setFamiliarityPercent(curation.familiarity_percent ?? 70); setPeriodStart(curation.period_start || "18:00"); setPeriodEnd(curation.period_end || "23:00");
    setTrackLimit(curation.track_limit); setRefreshMode(curation.refresh_mode); setRefreshEnabled(curation.refresh_enabled);
    setPreview({ tracks: curation.tracks, references: curation.recipe?.references || { positive: [], negative: [] }, weights: curation.recipe?.weights, familiarity: curation.recipe?.familiarity, corpus_size: 0 });
    setDetailKind("saved"); setMobilePane("playlists");
  }
  function resetRecipeForm() {
    setName(""); setCurationType("language"); setPositive(""); setNegative("");
    setSoundTags([]); setThemeTags([]); setSoundWeight(50);
    setPositiveTracks([]); setNegativeTracks([]);
    setFamiliarityPercent(70); setPeriodStart("18:00"); setPeriodEnd("23:00");
    setTrackLimit(30); setRefreshMode("stable"); setRefreshEnabled(true); setError("");
  }
  function closeDetails() {
    if (detailKind === "saved") resetRecipeForm();
    setPreview(null); setDetailKind(null);
  }

  const shown = preview?.tracks || [];
  const columns = [0.35, 0.04, 0.61];
  return <AppShell title="Curate" footer={<CopyrightFooter />} breadcrumb flush fullPage grid={{ columns, rows: [1] }}>
    <main className={styles.page} style={{ gridTemplateColumns: trackTemplate(columns, 180), gridTemplateRows: trackTemplate([1], 152) }}>
      <nav className={styles.mobilePivots} aria-label="Curation sections"><button className={mobilePane === "recipe" ? styles.activePivot : ""} onClick={() => setMobilePane("recipe")}>recipe</button><button className={mobilePane === "playlists" ? styles.activePivot : ""} onClick={() => setMobilePane("playlists")}>playlists <b>{curations.length}</b></button></nav>
      <section className={`${styles.recipe} ${mobilePane === "recipe" ? styles.mobileActive : ""}`}>
        <header><h1>Build playlists</h1><p>Describe what belongs and what does not. Named tracks, artists, and albums become explicit examples.</p></header>
        <nav className={styles.types} aria-label="Curation type"><button className={curationType === "language" ? styles.activeType : ""} onClick={() => setCurationType("language")}><MessageSquareText /><span>Language</span></button><button className={curationType === "examples" ? styles.activeType : ""} onClick={() => setCurationType("examples")}><ListMusic /><span>Like / not like</span></button><button className={curationType === "time_of_day" ? styles.activeType : ""} onClick={() => setCurationType("time_of_day")}><Clock3 /><span>Time of day</span>{!historyConnected && <small>Needs Last.fm</small>}</button></nav>
        <label><span>Playlist name</span><input value={name} onChange={event => setName(event.target.value)} placeholder="Late-night circuitry" /></label>
        {curationType === "language" && <>{legacy && positive.trim() && <label><span>Positive direction · matched to sound and lyrics</span><textarea value={positive} onChange={event => setPositive(event.target.value)} placeholder="Dreamy electronic music with soft vocals and patient builds" /></label>}<Alert tone="info" className={styles.tagHelp}><b>Enter</b> adds each tag. <b className={styles.plus}>+guitars</b> matches guitar music; <b className={styles.minus}>-synths</b> keeps it out. <b>Sound</b> tags score against the recording, <b>themes</b> tags against the lyrics.</Alert><TagInput label="Sound · instruments and production" placeholder="guitars · -synths · Enter to add" tags={soundTags} onChange={setSoundTags} />{sound.positive.length > 0 && themes.positive.length > 0 && <div className={styles.familiarity}><header><span>Blend</span><b>{soundWeight}% sound · {100 - soundWeight}% themes</b></header><input type="range" min="0" max="100" step="5" value={soundWeight} onChange={event => setSoundWeight(Number(event.target.value))} aria-label="Sound and themes blend" /><small>How much the recording versus the lyrics decide the ranking.</small></div>}<TagInput label="Themes · what the words are about" placeholder="heartbreak · -party · Enter to add" tags={themeTags} onChange={setThemeTags} /></>}
        {curationType === "examples" && <><TrackReferencePicker label="Songs like" value={positiveTracks} onChange={setPositiveTracks} /><TrackReferencePicker label="Songs not like" value={negativeTracks} onChange={setNegativeTracks} /></>}
        {curationType === "time_of_day" && <section className={styles.timeScaffold}><header><Clock3 /><div><strong>Recurring listening period</strong><small>Playlist generation uses the previous seven days of Last.fm history.</small></div></header><div><label><span>From</span><input type="time" value={periodStart} onChange={event => setPeriodStart(event.target.value)} /></label><label><span>Until</span><input type="time" value={periodEnd} onChange={event => setPeriodEnd(event.target.value)} /></label></div><p>Overnight periods are supported. Listening periods use the timezone selected in Settings.</p></section>}
        <div className={styles.familiarity}><header><span>Listening mix</span><b>{familiarityPercent}% familiar · {100 - familiarityPercent}% discovery</b></header><input type="range" min="0" max="100" step="5" value={familiarityPercent} onChange={event => setFamiliarityPercent(Number(event.target.value))} aria-label="Familiar and discovery track mix" /><small>{historyConnected ? "Applied using the previous seven days of matched Last.fm listens." : "Inactive until Last.fm listening history is connected. This setting is saved with the playlist."}</small></div>
        <div className={styles.controls}><label><span>Tracks</span><input type="number" min="5" max="200" value={trackLimit} onChange={event => setTrackLimit(Number(event.target.value))} /></label><label><span>Refresh style</span><select value={refreshMode} onChange={event => setRefreshMode(event.target.value as "stable" | "fresh")}><option value="stable">Stable</option><option value="fresh">Fresh</option></select></label></div>
        <button className={styles.schedule} onClick={() => setRefreshEnabled(value => !value)}><Clock3 /><span>Refresh every 6 hours</span><b>{refreshEnabled ? "ON" : "OFF"}</b></button>
        <div className={styles.actions}><button onClick={generate} disabled={busy || !hasPositiveEvidence}><WandSparkles />{busyAction === "preview" ? "CURATING" : "PREVIEW"}</button><button onClick={save} disabled={busy || !hasPositiveEvidence}><Save />{busyAction === "save" ? "SAVING" : "SAVE + SYNC"}</button></div>
        {error && <Alert tone="error" className={styles.actionError}>{error}</Alert>}
      </section>
      <section className={`${styles.results} ${mobilePane === "playlists" ? styles.mobileActive : ""}`}>
        {preview ? <div className={`${styles.panelView} ${styles.detailView}`}>
          <header><button className={styles.back} onClick={closeDetails} aria-label="Back to saved curations"><ArrowLeft /></button><h2>{name || "Temporary preview"}</h2><strong>{shown.length}</strong></header>
          {preview.references && <div className={styles.references}>{(["positive", "negative"] as const).map(kind => preview.references[kind].map(reference => <span className={kind === "negative" ? styles.negative : ""} key={`${kind}-${reference.kind}-${reference.name}`}>{reference.kind} · {reference.name}</span>))}</div>}
          <div className={styles.trackList}>{shown.length ? shown.map((track, index) => <article key={track.id}><b>{String(index + 1).padStart(2, "0")}</b><div className={styles.art}>{track.cover_art && connectionId ? <LoadingImage sizes="46px" src={`/analysis/navidrome/connections/${connectionId}/cover/${track.cover_art}`} alt="" /> : <Disc3 />}</div><div><strong>{track.title}</strong><small className={styles.trackMeta}><span>{track.artist || "Unknown artist"} · {track.album || "Unknown album"}</span>{track.evidence?.selection_pool === "familiar" && <em className={styles.historyBadge} title={`${track.evidence.listen_count || 0} matched Last.fm listens`}>LAST.FM PICK</em>}</small></div><span>{track.percentile == null ? track.score.toFixed(2) : `TOP ${Math.max(1, Math.round((1 - track.percentile) * 100))}%`}</span><button onClick={() => current?.id === track.id ? toggle() : playQueue(playerTracks(shown), index)} aria-label={`Play ${track.title}`}>{current?.id === track.id && playing ? <Pause /> : <Play />}</button></article>) : <p>This curation does not have a completed playlist yet.</p>}</div>
          {shown.length > 0 && <footer><button onClick={() => playQueue(playerTracks(shown), 0)}><Play /> {detailKind === "saved" ? "PLAY PLAYLIST" : "PLAY PREVIEW"}</button><span>{preview.familiarity?.active ? `${preview.familiarity.familiar_tracks} familiar · ${preview.familiarity.discovery_tracks} discovery · shuffled` : preview.weights ? `${Math.round(preview.weights.semantic * 100)}% sound · ${Math.round(preview.weights.lyrics * 100)}% themes` : "45% MuQ-MuLan sound · 55% BGE-M3 lyrics"}</span></footer>}
        </div> : <div className={`${styles.panelView} ${styles.curationView}`}>
          <header><div><h2>Saved curations</h2><p>Your synced playlists and their latest revisions.</p></div><strong>{curations.length}</strong></header>
          <div className={styles.curationList}>{curations.length ? curations.map(curation => <article key={curation.id} className={styles.curationCard}><button className={styles.curationMain} onClick={() => openCuration(curation)}><span data-status={curation.status} title={curation.status === "ready" ? "Latest playlist revision is synced" : curation.status === "refreshing" ? "A new playlist revision is being generated" : curation.status === "failed" ? "The latest refresh failed" : "Playlist has not been generated yet"}>{curation.status}</span><strong>{curation.name}</strong><small>{curation.tracks.length} tracks · {curation.refresh_enabled ? "refreshes every 6 hours" : "manual refresh"}</small>{curation.last_error && <em>{curation.last_error}</em>}</button><button title="Refresh now" disabled={busy} onClick={() => refresh(curation)}><RefreshCw /></button><button title="Toggle schedule" className={curation.refresh_enabled ? styles.enabled : ""} onClick={() => toggleSchedule(curation)}><Clock3 /></button><button title="Delete curation" className={styles.deleteButton} onClick={() => setDeleteTarget(curation)}><Trash2 /></button></article>) : <div className={styles.emptyCurations}><ListMusic /><strong>No saved curations</strong><p>Build a recipe on the left, then use Save + Sync to publish it.</p></div>}</div>
        </div>}
      </section>
      {deleteTarget && <div className={styles.deleteScrim} role="presentation" onMouseDown={event => { if (event.target === event.currentTarget && !busy) setDeleteTarget(null); }}><section className={styles.deleteDialog} role="dialog" aria-modal="true" aria-labelledby="delete-curation-title"><header><div><span>Delete curation</span><h2 id="delete-curation-title">{deleteTarget.name}</h2></div><button onClick={() => setDeleteTarget(null)} disabled={busy} aria-label="Close delete dialog"><X /></button></header><p>Choose whether the synced playlist should remain in Navidrome.</p><div><button className={styles.keepRemote} onClick={() => removeCuration(false)} disabled={busy}>DELETE FROM ECHORA ONLY<small>Keep the playlist in Navidrome</small></button><button className={styles.deleteEverywhere} onClick={() => removeCuration(true)} disabled={busy}><Trash2 />DELETE BOTH<small>Remove it from Echora and Navidrome</small></button></div></section></div>}
    </main>
  </AppShell>;
}
