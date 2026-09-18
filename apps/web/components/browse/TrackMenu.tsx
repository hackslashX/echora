"use client";

import { Languages, ListPlus, Menu, Music2, Play, SquarePen, VolumeX, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { PlayerTrack } from "../player/PlayerProvider";
import { usePlayer } from "../player/PlayerProvider";
import CardHeader from "../ui/CardHeader";
import styles from "./TrackMenu.module.css";

type Track = { id: string; title: string; artist?: string; duration_seconds: number; source_id?: string; connectionId?: string; streamUrl?: string; coverUrl?: string; lyrics_status?: string; lyrics_text?: string; lyrics_language?: string };
type Lyrics = { text?: string | null; language?: string | null; availability_status?: string | null };

export default function TrackMenu({ track, onSaved }: { track: Track; onSaved: () => void }) {
  const player = usePlayer();
  const rootRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [transcriptionOpen, setTranscriptionOpen] = useState(false);
  const [transcriptionLanguage, setTranscriptionLanguage] = useState("");
  const [lyrics, setLyrics] = useState("");
  const [language, setLanguage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const playable = Boolean(track.streamUrl && track.source_id);
  const playerTrack: PlayerTrack | null = playable ? { id: track.id, title: track.title, artist: track.artist, durationSeconds: track.duration_seconds, streamUrl: track.streamUrl!, coverUrl: track.coverUrl, connectionId: track.connectionId, sourceId: track.source_id } : null;

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => { if (!rootRef.current?.contains(event.target as Node)) setOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    window.addEventListener("mousedown", close); window.addEventListener("keydown", escape);
    return () => { window.removeEventListener("mousedown", close); window.removeEventListener("keydown", escape); };
  }, [open]);

  async function openEditor() {
    setOpen(false); setError(""); setBusy(true);
    try {
      const response = await fetch(`/analysis/library/tracks/${encodeURIComponent(track.id)}/lyrics`);
      const body = await response.json() as Lyrics;
      if (!response.ok) throw new Error("Could not load lyrics");
      setLyrics(body.text || ""); setLanguage(body.language || ""); setEditorOpen(true);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not load lyrics"); }
    finally { setBusy(false); }
  }

  async function saveLyrics() {
    setBusy(true); setError("");
    try {
      const response = await fetch(`/analysis/library/tracks/${encodeURIComponent(track.id)}/lyrics`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ text: lyrics, language: language || null }) });
      const body = await response.json(); if (!response.ok) throw new Error(body.detail || "Could not save lyrics");
      setEditorOpen(false); window.dispatchEvent(new CustomEvent("echora:lyrics-update", { detail: track.id })); onSaved();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not save lyrics"); }
    finally { setBusy(false); }
  }

  async function forceTranscription() {
    setBusy(true); setError("");
    try {
      const response = await fetch(`/analysis/library/tracks/${encodeURIComponent(track.id)}/lyrics/transcription-language`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ language: transcriptionLanguage }) });
      const body = await response.json(); if (!response.ok) throw new Error(body.detail || "Could not queue transcription");
      setTranscriptionOpen(false); window.dispatchEvent(new CustomEvent("echora:lyrics-update", { detail: track.id })); onSaved();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not queue transcription"); }
    finally { setBusy(false); }
  }

  async function mark(status: "instrumental" | "missing") {
    setOpen(false); setBusy(true); setError("");
    try {
      const response = await fetch(`/analysis/library/tracks/${encodeURIComponent(track.id)}/lyrics/status`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ status }) });
      const body = await response.json(); if (!response.ok) throw new Error(body.detail || "Could not update lyric status");
      window.dispatchEvent(new CustomEvent("echora:lyrics-update", { detail: track.id })); onSaved();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not update lyric status"); }
    finally { setBusy(false); }
  }

  return <div className={styles.root} ref={rootRef} onClick={event => event.stopPropagation()}>
    <button type="button" className={styles.trigger} aria-label={`Actions for ${track.title}`} aria-expanded={open} onClick={() => setOpen(value => !value)}><Menu /></button>
    {open && <div className={styles.menu} role="menu">
      <button type="button" role="menuitem" disabled={!playerTrack} onClick={() => { if (playerTrack) player.play(playerTrack); setOpen(false); }}><Play />Play now</button>
      <button type="button" role="menuitem" disabled={!playerTrack} onClick={() => { if (playerTrack) player.playNext(playerTrack); setOpen(false); }}><ListPlus />Play next</button>
      <hr />
      <button type="button" role="menuitem" disabled={busy} onClick={openEditor}><SquarePen />Edit lyrics</button>
      <button type="button" role="menuitem" disabled={busy} onClick={() => { setOpen(false); setError(""); setTranscriptionOpen(true); }}><Languages />Transcribe in language</button>
      {track.lyrics_status === "instrumental" ? <button type="button" role="menuitem" disabled={busy} onClick={() => mark("missing")}><Music2 />Mark non-instrumental</button> : <button type="button" role="menuitem" disabled={busy} onClick={() => mark("instrumental")}><VolumeX />Mark instrumental</button>}
    </div>}
    {error && <span className={styles.error} role="alert">{error}</span>}
    {transcriptionOpen && <div className={styles.scrim} role="presentation" onMouseDown={event => { if (event.target === event.currentTarget && !busy) setTranscriptionOpen(false); }}><section className={styles.dialog} role="dialog" aria-modal="true" aria-label={`Force transcription for ${track.title}`}><CardHeader as="h2" eyebrow="Force transcription" title={track.title} description={track.artist} actions={<button type="button" onClick={() => setTranscriptionOpen(false)} disabled={busy} aria-label="Close transcription dialog"><X /></button>} /><label><span>Language code</span><input value={transcriptionLanguage} onChange={event => setTranscriptionLanguage(event.target.value)} placeholder="en or pt-BR" maxLength={5} /></label><p>This replaces the current lyrics and asks MOSS to transcribe in that language during the next sync. AI lyric generation must be enabled in Settings.</p>{error && <strong className={styles.dialogError}>{error}</strong>}<footer><button type="button" onClick={() => setTranscriptionOpen(false)} disabled={busy}>Cancel</button><button type="button" onClick={forceTranscription} disabled={busy || !/^[a-z]{2,3}(?:-[A-Z]{2})?$/.test(transcriptionLanguage)}>{busy ? "Queueing" : "Queue transcription"}</button></footer></section></div>}
    {editorOpen && <div className={styles.scrim} role="presentation" onMouseDown={event => { if (event.target === event.currentTarget && !busy) setEditorOpen(false); }}><section className={styles.dialog} role="dialog" aria-modal="true" aria-label={`Edit lyrics for ${track.title}`}><CardHeader as="h2" eyebrow="Lyrics" title={track.title} description={track.artist} actions={<button type="button" onClick={() => setEditorOpen(false)} disabled={busy} aria-label="Close lyric editor"><X /></button>} /><label><span>Language, optional</span><input value={language} onChange={event => setLanguage(event.target.value)} placeholder="en" maxLength={12} /></label><label><span>Lyrics</span><textarea value={lyrics} onChange={event => setLyrics(event.target.value)} placeholder="Paste or write the lyrics" /></label><p>Saving changed lyrics skips transcription and queues karaoke timing for the next sync.</p>{error && <strong className={styles.dialogError}>{error}</strong>}<footer><button type="button" onClick={() => setEditorOpen(false)} disabled={busy}>Cancel</button><button type="button" onClick={saveLyrics} disabled={busy || !lyrics.trim()}>{busy ? "Saving" : "Save lyrics"}</button></footer></section></div>}
  </div>;
}
