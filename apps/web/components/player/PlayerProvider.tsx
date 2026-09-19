"use client";

import { createContext, ReactNode, useContext, useEffect, useRef, useState } from "react";
import { sizedPlayerCoverArtUrl } from "../media/coverArt";
import { paletteFromPixels, type TrackPalette } from "./artworkPalette";
import FullscreenPlayer from "./FullscreenPlayer";
import { readPlaybackPreferences, streamUrlForQuality } from "./playbackPreferences";
import { mediaUrl } from "../media/mediaOrigin";

export type PlayerTrack = { id: string; title: string; artist?: string; album?: string; durationSeconds?: number; streamUrl: string; coverUrl?: string; connectionId?: string; sourceId?: string };

function scrobble(track: PlayerTrack | null, submission: boolean) {
  if (!track?.connectionId || !track.sourceId) return;
  fetch(mediaUrl("/navidrome/scrobble"), {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ connection_id: track.connectionId, song_id: track.sourceId, submission }),
  }).catch(() => {});
}
export type AudioQuality = { codec?: string; content_type?: string; bit_rate_kbps?: number; bit_depth?: number; sample_rate_hz?: number; channels?: number; lossless?: boolean; streamQuality: "original" | "320" | "120" };
export type PlayerLyrics = { trackId: string; available: boolean; karaoke?: boolean; lines?: { start_ms: number | null; end_ms?: number; text: string; syllables?: { start_ms: number; end_ms: number; text: string }[] }[]; text?: string; language?: string; provenance?: { ai_generated?: boolean; synced?: boolean; lines?: { start_ms: number | null; end_ms?: number; text: string; syllables?: { start_ms: number; end_ms: number; text: string }[] }[] } };
export type MelodyPreview = { source: string; points: { time_seconds: number; pitch: number | null }[] };
type VisualFeatureTimeline = { hop_seconds: number; bands: number[][]; level: number[]; centroid: number[]; flux: number[]; onset: number[]; chroma: number[][] };
type PlayerState = {
  track: PlayerTrack | null; audioQuality: AudioQuality | null; lyrics: PlayerLyrics | null; lyricsLoading: boolean; playing: boolean; buffering: boolean; currentTime: number; duration: number; buffered: number; muted: boolean; expanded: boolean;
  waveform: number[] | null; melody: MelodyPreview | null;
  queue: PlayerTrack[]; queueIndex: number;
  play: (track: PlayerTrack) => void; playQueue: (tracks: PlayerTrack[], startIndex?: number) => void; playNext: (track: PlayerTrack) => void;
  next: () => void; previous: () => void; clearQueue: () => void;
  toggle: () => void; seek: (seconds: number) => void; toggleMute: () => void; setExpanded: (value: boolean) => void;
};

const PlayerContext = createContext<PlayerState | null>(null);

const rgb = (color: [number, number, number]) => `rgb(${color.join(" ")})`;

function publishPalette(palette: TrackPalette | null) {
  const root = document.documentElement;
  if (palette) {
    root.style.setProperty("--accent-rgb", palette.accent.join(" "));
    root.style.setProperty("--aqua", rgb(palette.accent));
    root.style.setProperty("--line", `rgb(${palette.accent.join(" ")} / .28)`);
    root.style.setProperty("--glass-stroke", `rgb(${palette.accent.join(" ")} / .38)`);
  } else {
    root.style.removeProperty("--accent-rgb"); root.style.removeProperty("--aqua"); root.style.removeProperty("--line"); root.style.removeProperty("--glass-stroke");
  }
  window.dispatchEvent(new CustomEvent("echora:track-palette", { detail: { active: Boolean(palette), palette } }));
}

function hasMediaSession() {
  return typeof navigator !== "undefined" && "mediaSession" in navigator;
}

function publishMediaMetadata(track: PlayerTrack) {
  if (!hasMediaSession() || typeof MediaMetadata === "undefined") return;
  const artwork = track.coverUrl ? [{ src: new URL(sizedPlayerCoverArtUrl(track.coverUrl, 512), window.location.href).href }] : [];
  navigator.mediaSession.metadata = new MediaMetadata({
    title: track.title || "Unknown title",
    artist: track.artist || "Unknown artist",
    album: track.album || "",
    artwork,
  });
}

function publishMediaPosition(player: HTMLAudioElement, fallbackDuration = 0) {
  if (!hasMediaSession() || !navigator.mediaSession.setPositionState) return;
  const duration = Number.isFinite(player.duration) && player.duration > 0 ? player.duration : fallbackDuration;
  if (!Number.isFinite(duration) || duration <= 0) return;
  navigator.mediaSession.setPositionState({ duration, playbackRate: player.playbackRate || 1, position: Math.min(Math.max(player.currentTime || 0, 0), duration) });
}

async function artworkPalette(url: string): Promise<TrackPalette> {
  const image = new Image(); image.crossOrigin = "anonymous"; image.src = url;
  await image.decode();
  const size = 64;
  const canvas = document.createElement("canvas"); canvas.width = size; canvas.height = size;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) throw new Error("Canvas is unavailable");
  context.imageSmoothingEnabled = true; context.imageSmoothingQuality = "high";
  context.drawImage(image, 0, 0, size, size);
  const pixels = context.getImageData(0, 0, size, size).data;
  return paletteFromPixels(pixels);
}

export function PlayerProvider({ children }: { children: ReactNode }) {
  const audio = useRef<HTMLAudioElement | null>(null);
  const visualFeatures = useRef<VisualFeatureTimeline | null>(null);
  const analysisFrame = useRef(0);
  const queueRef = useRef<PlayerTrack[]>([]);
  const trackRef = useRef<PlayerTrack | null>(null);
  const paletteRef = useRef<TrackPalette | null>(null);
  const paletteTrackRef = useRef("");
  const lyricsCacheRef = useRef(new Map<string, PlayerLyrics>());
  const lyricsGenerationRef = useRef(new Map<string, number>());
  const queueIndexRef = useRef(-1);
  const activateQueueIndexRef = useRef<(index: number) => void>(() => {});
  const nextRef = useRef<() => void>(() => {});
  const previousRef = useRef<() => void>(() => {});
  const listenedRef = useRef(0);
  const announcedRef = useRef("");
  const [track, setTrack] = useState<PlayerTrack | null>(null);
  const [waveformData, setWaveformData] = useState<{ trackId: string; peaks: number[] | null; melody: MelodyPreview | null } | null>(null);
  const waveform = waveformData?.trackId === track?.id ? waveformData?.peaks ?? null : null;
  const melody = waveformData?.trackId === track?.id ? waveformData?.melody ?? null : null;
  useEffect(() => {
    if (!track?.id) return;
    const trackId = track.id;
    visualFeatures.current = null;
    const controller = new AbortController();
    fetch(`/analysis/library/tracks/${encodeURIComponent(trackId)}/visual-features`, { signal: controller.signal })
      .then(response => response.ok ? response.json() : null)
      .then(body => {
        const value = body?.visual_features?.features;
        if (!value || !Array.isArray(value.bands) || !Array.isArray(value.level) || !Number.isFinite(value.hop_seconds)) return;
        const frameCount = value.bands.length;
        if (!frameCount || value.level.length !== frameCount || !value.bands.every((frame: unknown) => Array.isArray(frame))) return;
        visualFeatures.current = value as VisualFeatureTimeline;
      }).catch(() => {});
    fetch(`/analysis/library/tracks/${encodeURIComponent(trackId)}/waveform`, { signal: controller.signal })
      .then(response => response.ok ? response.json() : null)
      .then(body => {
        const peaks = body?.waveform?.peaks;
        const validPeaks = Array.isArray(peaks) && peaks.length > 0 && peaks.length <= 1024 && peaks.every(value => typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1);
        const melody = body?.melody;
        const validMelody = melody && typeof melody.source === "string" && Array.isArray(melody.points) && melody.points.length <= 1024 && melody.points.every((point: { time_seconds?: unknown; pitch?: unknown }) => typeof point.time_seconds === "number" && Number.isFinite(point.time_seconds) && point.time_seconds >= 0 && (point.pitch === null || typeof point.pitch === "number" && Number.isFinite(point.pitch)));
        if (!controller.signal.aborted) setWaveformData({ trackId, peaks: validPeaks ? peaks : null, melody: validMelody ? melody : null });
      }).catch(() => {});
    return () => controller.abort();
  }, [track?.id]);
  const [audioQuality, setAudioQuality] = useState<AudioQuality | null>(null);
  const [lyrics, setLyrics] = useState<PlayerLyrics | null>(null);
  const [lyricsLoading, setLyricsLoading] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [buffering, setBuffering] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [buffered, setBuffered] = useState(0);
  const [muted, setMuted] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [queue, setQueue] = useState<PlayerTrack[]>([]);
  const [queueIndex, setQueueIndex] = useState(-1);

  useEffect(() => {
    const player = new Audio(); audio.current = player;
    const time = () => { listenedRef.current = player.currentTime || 0; setCurrentTime(player.currentTime || 0); publishMediaPosition(player, trackRef.current?.durationSeconds); };
    const metadata = () => {
      const canonical = trackRef.current?.durationSeconds;
      setDuration(current => canonical && canonical > 0 ? canonical : Number.isFinite(player.duration) && player.duration > 0 ? player.duration : current);
      publishMediaPosition(player, canonical);
    };
    const progress = () => setBuffered(player.buffered.length ? player.buffered.end(player.buffered.length - 1) : 0);
    const ended = () => { scrobble(trackRef.current, true); window.dispatchEvent(new CustomEvent("echora:playback-state", { detail: false })); publishPalette(null); if (queueIndexRef.current >= 0 && queueIndexRef.current < queueRef.current.length - 1) activateQueueIndexRef.current(queueIndexRef.current + 1); else setPlaying(false); };
    const paused = () => { window.dispatchEvent(new CustomEvent("echora:playback-state", { detail: false })); setPlaying(false); publishPalette(null); if (hasMediaSession()) navigator.mediaSession.playbackState = "paused"; };
    const waiting = () => setBuffering(true);
    const ready = () => setBuffering(false);
    const started = () => { window.dispatchEvent(new CustomEvent("echora:playback-state", { detail: true })); setPlaying(true); setBuffering(false); publishPalette(paletteRef.current); if (hasMediaSession()) navigator.mediaSession.playbackState = "playing"; publishMediaPosition(player, trackRef.current?.durationSeconds); const current = trackRef.current; if (current?.sourceId && announcedRef.current !== current.sourceId + player.currentSrc) { announcedRef.current = current.sourceId + player.currentSrc; scrobble(current, false); } };
    const setAction = (action: MediaSessionAction, handler: MediaSessionActionHandler | null) => { try { navigator.mediaSession.setActionHandler(action, handler); } catch {} };
    if (hasMediaSession()) {
      setAction("play", () => { startAnalysis(); player.play().catch(() => setPlaying(false)); });
      setAction("pause", () => player.pause());
      setAction("previoustrack", () => previousRef.current());
      setAction("nexttrack", () => nextRef.current());
      setAction("seekbackward", details => seek(Math.max(0, player.currentTime - (details.seekOffset || 10))));
      setAction("seekforward", details => seek(player.currentTime + (details.seekOffset || 10)));
      setAction("seekto", details => { if (typeof details.seekTime === "number") seek(details.seekTime); });
    }
    // Backdrop canvases live outside this provider, so they request the current
    // state instead of relying on a playback event that may have already fired.
    const reportPlaybackState = () => window.dispatchEvent(new CustomEvent("echora:playback-state", { detail: !player.paused && Boolean(trackRef.current) }));
    window.addEventListener("echora:playback-state-request", reportPlaybackState);
    player.addEventListener("timeupdate", time); player.addEventListener("durationchange", metadata);
    player.addEventListener("loadedmetadata", metadata); player.addEventListener("progress", progress); player.addEventListener("ended", ended);
    player.addEventListener("pause", paused); player.addEventListener("play", started);
    player.addEventListener("loadstart", waiting); player.addEventListener("waiting", waiting);
    player.addEventListener("canplay", ready); player.addEventListener("playing", ready);
    return () => { window.removeEventListener("echora:playback-state-request", reportPlaybackState); player.pause(); publishPalette(null); if (hasMediaSession()) { navigator.mediaSession.metadata = null; navigator.mediaSession.playbackState = "none"; ["play", "pause", "previoustrack", "nexttrack", "seekbackward", "seekforward", "seekto"].forEach(action => setAction(action as MediaSessionAction, null)); } cancelAnimationFrame(analysisFrame.current); analysisFrame.current = 0; player.remove(); };
  }, []);

  function startAnalysis() {
    const player = audio.current;
    if (!player || analysisFrame.current) return;
    // The server builds this timeline during library processing. Every visualizer
    // receives the same bands and onset values, so no visualizer owns an FFT.
    let lastAnalysis = 0;
    let previousIndex = -1;
    let previousBands: number[] = [];
    const analyze = (now = performance.now()) => {
      analysisFrame.current = requestAnimationFrame(analyze);
      if (now - lastAnalysis < (player.paused ? 500 : 1000 / 30)) return;
      lastAnalysis = now;
      const timeline = visualFeatures.current;
      if (!timeline || player.paused) return;
      const index = Math.min(timeline.bands.length - 1, Math.max(0, Math.floor(player.currentTime / timeline.hop_seconds)));
      const bands = timeline.bands[index];
      if (!bands?.length) return;
      const band = (from: number, to: number) => {
        let sum = 0;
        for (let item = from; item < to; item += 1) sum += bands[item] || 0;
        return sum / Math.max(1, to - from);
      };
      const bass = band(0, 7), mid = band(7, 17), treble = band(17, bands.length);
      const onset = index !== previousIndex && (timeline.onset[index] || 0) >= .38;
      const bassAttack = Math.max(0, bass - (previousBands[0] || 0));
      const midAttack = Math.max(0, mid - (previousBands[1] || 0));
      const trebleAttack = Math.max(0, treble - (previousBands[2] || 0));
      previousIndex = index; previousBands = [bass, mid, treble];
      const spectrum = new Uint8Array(512);
      for (let item = 0; item < spectrum.length; item += 1) spectrum[item] = Math.round((bands[Math.min(bands.length - 1, Math.floor(item * bands.length / spectrum.length))] || 0) * 255);
      const waveform = new Uint8Array(256);
      for (let item = 0; item < waveform.length; item += 1) waveform[item] = Math.round(128 + Math.sin(item / waveform.length * Math.PI * 8) * (timeline.level[index] || 0) * 80);
      window.dispatchEvent(new CustomEvent("echora:audio-spectrum", { detail: spectrum }));
      window.dispatchEvent(new CustomEvent("echora:audio-waveform", { detail: waveform }));
      window.dispatchEvent(new CustomEvent("echora:audio-reactivity", { detail: {
        bass, mid, treble, onset, timestamp: player.currentTime,
        level: timeline.level[index] || 0, bassAttack, midAttack, trebleAttack,
      } }));
      window.dispatchEvent(new CustomEvent("echora:playback-time", { detail: player.currentTime || 0 }));
    };
    analyze();
  }

  function loadLyrics(next: PlayerTrack) {
    const cached = lyricsCacheRef.current.get(next.id);
    if (cached) { setLyrics(cached); setLyricsLoading(false); return; }
    setLyrics(null); setLyricsLoading(true);
    const generation = lyricsGenerationRef.current.get(next.id) || 0;
    const resolve = (value: unknown) => {
      // A save may have invalidated this request while it was in flight.
      if ((lyricsGenerationRef.current.get(next.id) || 0) !== generation) return;
      const resolved: PlayerLyrics = value ? { ...(value as PlayerLyrics), trackId: next.id } : { trackId: next.id, available: false };
      lyricsCacheRef.current.set(next.id, resolved);
      if (trackRef.current?.id === next.id) { setLyrics(resolved); setLyricsLoading(false); }
    };
    fetch(`/analysis/library/tracks/${next.id}/lyrics`).then(response => response.ok ? response.json() : null).then(resolve).catch(() => resolve(null));
  }

  function load(next: PlayerTrack) {
    const player = audio.current; if (!player) return;
    const previous = trackRef.current;
    if (previous?.sourceId && previous.sourceId !== next.sourceId) {
      const seconds = listenedRef.current;
      if (seconds >= (previous.durationSeconds || 0) / 2 || seconds >= 240) scrobble(previous, true);
    }
    listenedRef.current = 0; announcedRef.current = "";
    paletteRef.current = null; paletteTrackRef.current = next.id; trackRef.current = next; setBuffered(0); setBuffering(true); publishPalette(null); window.dispatchEvent(new CustomEvent("echora:track-change", { detail: next.id }));
    publishMediaMetadata(next);
    loadLyrics(next);
    if (next.coverUrl) artworkPalette(sizedPlayerCoverArtUrl(next.coverUrl, 128)).then(palette => {
      if (paletteTrackRef.current !== next.id) return;
      paletteRef.current = palette;
      if (!audio.current?.paused) publishPalette(palette);
    }).catch(() => {});
    const streamQuality = readPlaybackPreferences().quality;
    setAudioQuality(null);
    fetch(`/analysis/library/tracks/${next.id}/audio-quality`).then(response => response.ok ? response.json() : null).then(value => {
      if (value && trackRef.current?.id === next.id) setAudioQuality({ ...value, streamQuality });
    }).catch(() => {});
    startAnalysis(); player.src = streamUrlForQuality(next.streamUrl, streamQuality); setTrack(next); setCurrentTime(0); setDuration(next.durationSeconds || 0);
    player.play().catch(() => setPlaying(false));
  }
  function activateQueueIndex(index: number) {
    const nextTrack = queueRef.current[index]; if (!nextTrack) return;
    queueIndexRef.current = index; setQueueIndex(index); load(nextTrack);
  }
  activateQueueIndexRef.current = activateQueueIndex;
  function play(next: PlayerTrack) {
    const player = audio.current; if (!player) return;
    if (track?.id !== next.id) { queueRef.current = [next]; queueIndexRef.current = 0; setQueue([next]); setQueueIndex(0); load(next); }
    else { startAnalysis(); player.play().catch(() => setPlaying(false)); }
  }
  function playQueue(tracks: PlayerTrack[], startIndex = 0) {
    if (!tracks.length) return;
    const index = Math.min(Math.max(startIndex, 0), tracks.length - 1);
    queueRef.current = tracks; queueIndexRef.current = index; setQueue(tracks); setQueueIndex(index); load(tracks[index]);
  }
  function playNext(next: PlayerTrack) {
    const current = trackRef.current;
    if (!current || queueIndexRef.current < 0) { play(next); return; }
    if (current.id === next.id) return;
    const queue = queueRef.current.filter(item => item.id !== next.id);
    const currentIndex = queue.findIndex(item => item.id === current.id);
    const insertAt = currentIndex < 0 ? queue.length : currentIndex + 1;
    queue.splice(insertAt, 0, next);
    queueIndexRef.current = currentIndex; setQueueIndex(currentIndex);
    queueRef.current = queue; setQueue(queue);
  }
  function next() { if (queueIndexRef.current < queueRef.current.length - 1) activateQueueIndex(queueIndexRef.current + 1); }
  function previous() {
    const player = audio.current; if (!player) return;
    if (player.currentTime > 4 || queueIndexRef.current <= 0) { seek(0); return; }
    activateQueueIndex(queueIndexRef.current - 1);
  }
  nextRef.current = next;
  previousRef.current = previous;
  function clearQueue() { queueRef.current = track ? [track] : []; queueIndexRef.current = track ? 0 : -1; setQueue(queueRef.current); setQueueIndex(queueIndexRef.current); }
  function toggle() { const player = audio.current; if (!player || !track) return; startAnalysis(); if (player.paused) player.play(); else player.pause(); }
  function seek(seconds: number) { const player = audio.current; if (!player || !Number.isFinite(seconds)) return; player.currentTime = seconds; setCurrentTime(seconds); publishMediaPosition(player, trackRef.current?.durationSeconds); }
  function toggleMute() { const player = audio.current; if (!player) return; player.muted = !player.muted; setMuted(player.muted); }

  useEffect(() => {
    const invalidate = (event: Event) => {
      const trackId = (event as CustomEvent<string>).detail;
      if (typeof trackId !== "string") return;
      lyricsCacheRef.current.delete(trackId);
      lyricsGenerationRef.current.set(trackId, (lyricsGenerationRef.current.get(trackId) || 0) + 1);
      if (trackRef.current?.id === trackId) loadLyrics(trackRef.current);
    };
    window.addEventListener("echora:lyrics-update", invalidate);
    return () => window.removeEventListener("echora:lyrics-update", invalidate);
  }, []);

  return <PlayerContext.Provider value={{ track, waveform, melody, audioQuality, lyrics, lyricsLoading, playing, buffering, currentTime, duration, buffered, muted, expanded, queue, queueIndex, play, playQueue, playNext, next, previous, clearQueue, toggle, seek, toggleMute, setExpanded }}>{children}{expanded && track && <FullscreenPlayer />}</PlayerContext.Provider>;
}

export function usePlayer() {
  const value = useContext(PlayerContext);
  if (!value) throw new Error("usePlayer must be used inside PlayerProvider");
  return value;
}
