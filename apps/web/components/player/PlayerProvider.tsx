"use client";

import { createContext, ReactNode, useContext, useEffect, useRef, useState } from "react";
import { sizedPlayerCoverArtUrl } from "../media/coverArt";
import FullscreenPlayer from "./FullscreenPlayer";
import { readPlaybackPreferences, streamUrlForQuality } from "./playbackPreferences";

export type PlayerTrack = { id: string; title: string; artist?: string; album?: string; durationSeconds?: number; streamUrl: string; coverUrl?: string };
export type AudioQuality = { codec?: string; content_type?: string; bit_rate_kbps?: number; bit_depth?: number; sample_rate_hz?: number; channels?: number; lossless?: boolean; streamQuality: "original" | "320" | "120" };
export type PlayerLyrics = { trackId: string; available: boolean; karaoke?: boolean; lines?: { start_ms: number | null; end_ms?: number; text: string; syllables?: { start_ms: number; end_ms: number; text: string }[] }[]; text?: string; language?: string; provenance?: { synced?: boolean; lines?: { start_ms: number | null; end_ms?: number; text: string; syllables?: { start_ms: number; end_ms: number; text: string }[] }[] } };
type PlayerState = {
  track: PlayerTrack | null; audioQuality: AudioQuality | null; lyrics: PlayerLyrics | null; lyricsLoading: boolean; playing: boolean; buffering: boolean; currentTime: number; duration: number; buffered: number; muted: boolean; expanded: boolean;
  queue: PlayerTrack[]; queueIndex: number;
  play: (track: PlayerTrack) => void; playQueue: (tracks: PlayerTrack[], startIndex?: number) => void;
  next: () => void; previous: () => void; clearQueue: () => void;
  toggle: () => void; seek: (seconds: number) => void; toggleMute: () => void; setExpanded: (value: boolean) => void;
};

const PlayerContext = createContext<PlayerState | null>(null);

type TrackPalette = { accent: [number, number, number]; background: [number, number, number]; waves: [[number, number, number], [number, number, number], [number, number, number]] };
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
  type Bucket = { count: number; sum: [number, number, number] };
  const buckets = new Map<string, Bucket>();
  const average: [number, number, number] = [0, 0, 0];
  let samples = 0;
  for (let pixel = 0; pixel < size * size; pixel += 2) {
    const index = pixel * 4;
    if (pixels[index + 3] < 180) continue;
    const color: [number, number, number] = [pixels[index], pixels[index + 1], pixels[index + 2]];
    const high = Math.max(...color), low = Math.min(...color);
    if (high < 18 || low > 244) continue;
    color.forEach((value, channel) => { average[channel] += value; }); samples += 1;
    const key = color.map(value => Math.floor(value / 24)).join(":");
    const bucket = buckets.get(key) || { count: 0, sum: [0, 0, 0] };
    bucket.count += 1; color.forEach((value, channel) => { bucket.sum[channel] += value; }); buckets.set(key, bucket);
  }
  if (!samples || !buckets.size) throw new Error("Artwork has no usable colors");
  const clusters = [...buckets.values()].map(bucket => ({
    count: bucket.count,
    color: bucket.sum.map(value => value / bucket.count) as [number, number, number],
  }));
  const colorfulness = (color: [number, number, number]) => (Math.max(...color) - Math.min(...color)) / 255;
  const luminance = (color: [number, number, number]) => (color[0] * .2126 + color[1] * .7152 + color[2] * .0722) / 255;
  clusters.sort((left, right) => {
    const score = (cluster: typeof left) => cluster.count * (.3 + colorfulness(cluster.color) * 1.7) * (.65 + Math.min(.65, luminance(cluster.color)));
    return score(right) - score(left);
  });
  const accentSource = clusters[0].color;
  const readable = (color: [number, number, number]) => {
    const light = luminance(color);
    const mix = light < .48 ? Math.min(.52, (.48 - light) * 1.35) : 0;
    return color.map(value => Math.round(value + (255 - value) * mix)) as [number, number, number];
  };
  const accent = readable(accentSource);
  const background = average.map(value => Math.round(value / samples * .2 + 3)) as [number, number, number];
  const distance = (left: [number, number, number], right: [number, number, number]) => left.reduce((sum, value, channel) => sum + Math.abs(value - right[channel]), 0);
  const distinct = clusters.find(cluster => cluster.count >= samples * .008 && distance(cluster.color, accentSource) > 120)?.color || clusters[1]?.color || accentSource;
  const normalized = (color: [number, number, number]) => color.map(value => Math.min(1, Math.max(.12, value / 255))) as [number, number, number];
  return { accent, background, waves: [normalized(accentSource), normalized(distinct), normalized(accent)] };
}

export function PlayerProvider({ children }: { children: ReactNode }) {
  const audio = useRef<HTMLAudioElement | null>(null);
  const audioContext = useRef<AudioContext | null>(null);
  const analyser = useRef<AnalyserNode | null>(null);
  const analysisFrame = useRef(0);
  const queueRef = useRef<PlayerTrack[]>([]);
  const trackRef = useRef<PlayerTrack | null>(null);
  const paletteRef = useRef<TrackPalette | null>(null);
  const paletteTrackRef = useRef("");
  const lyricsCacheRef = useRef(new Map<string, PlayerLyrics>());
  const lyricsRequestsRef = useRef(new Set<string>());
  const queueIndexRef = useRef(-1);
  const activateQueueIndexRef = useRef<(index: number) => void>(() => {});
  const [track, setTrack] = useState<PlayerTrack | null>(null);
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
    const time = () => { setCurrentTime(player.currentTime || 0); publishMediaPosition(player, trackRef.current?.durationSeconds); };
    const metadata = () => {
      const canonical = trackRef.current?.durationSeconds;
      setDuration(current => canonical && canonical > 0 ? canonical : Number.isFinite(player.duration) && player.duration > 0 ? player.duration : current);
      publishMediaPosition(player, canonical);
    };
    const progress = () => setBuffered(player.buffered.length ? player.buffered.end(player.buffered.length - 1) : 0);
    const ended = () => { publishPalette(null); if (queueIndexRef.current >= 0 && queueIndexRef.current < queueRef.current.length - 1) activateQueueIndexRef.current(queueIndexRef.current + 1); else setPlaying(false); };
    const paused = () => { setPlaying(false); publishPalette(null); if (hasMediaSession()) navigator.mediaSession.playbackState = "paused"; };
    const waiting = () => setBuffering(true);
    const ready = () => setBuffering(false);
    const started = () => { setPlaying(true); setBuffering(false); publishPalette(paletteRef.current); if (hasMediaSession()) navigator.mediaSession.playbackState = "playing"; publishMediaPosition(player, trackRef.current?.durationSeconds); };
    const setAction = (action: MediaSessionAction, handler: MediaSessionActionHandler | null) => { try { navigator.mediaSession.setActionHandler(action, handler); } catch {} };
    if (hasMediaSession()) {
      setAction("play", () => { startAnalysis(); player.play().catch(() => setPlaying(false)); });
      setAction("pause", () => player.pause());
      setAction("previoustrack", previous);
      setAction("nexttrack", next);
      setAction("seekbackward", details => seek(Math.max(0, player.currentTime - (details.seekOffset || 10))));
      setAction("seekforward", details => seek(player.currentTime + (details.seekOffset || 10)));
      setAction("seekto", details => { if (typeof details.seekTime === "number") seek(details.seekTime); });
    }
    player.addEventListener("timeupdate", time); player.addEventListener("durationchange", metadata);
    player.addEventListener("loadedmetadata", metadata); player.addEventListener("progress", progress); player.addEventListener("ended", ended);
    player.addEventListener("pause", paused); player.addEventListener("play", started);
    player.addEventListener("loadstart", waiting); player.addEventListener("waiting", waiting);
    player.addEventListener("canplay", ready); player.addEventListener("playing", ready);
    return () => { player.pause(); publishPalette(null); if (hasMediaSession()) { navigator.mediaSession.metadata = null; navigator.mediaSession.playbackState = "none"; ["play", "pause", "previoustrack", "nexttrack", "seekbackward", "seekforward", "seekto"].forEach(action => setAction(action as MediaSessionAction, null)); } cancelAnimationFrame(analysisFrame.current); audioContext.current?.close(); player.remove(); };
  }, []);

  function startAnalysis() {
    const player = audio.current;
    if (!player || analyser.current) { audioContext.current?.resume(); return; }
    const browser = window as Window & { webkitAudioContext?: typeof AudioContext };
    const Context = window.AudioContext || browser.webkitAudioContext;
    if (!Context) return;
    const context = new Context();
    const node = context.createAnalyser();
    node.fftSize = 1024; node.smoothingTimeConstant = 0.55;
    const source = context.createMediaElementSource(player);
    source.connect(node); node.connect(context.destination);
    audioContext.current = context; analyser.current = node;
    const frequencies = new Uint8Array(node.frequencyBinCount);
    const waveform = new Uint8Array(node.fftSize);
    let lastAnalysis = 0;
    let bassFloor = 0;
    let lastOnset = -Infinity;
    let lastBass = 0, lastMid = 0, lastTreble = 0;
    const average = (from: number, to: number) => {
      let sum = 0; const end = Math.min(to, frequencies.length);
      for (let index = from; index < end; index++) sum += frequencies[index];
      return end > from ? sum / (end - from) / 255 : 0;
    };
    const analyze = (now = performance.now()) => {
      analysisFrame.current = requestAnimationFrame(analyze);
      if (now - lastAnalysis < (player.paused ? 500 : 1000 / 30)) return;
      lastAnalysis = now;
      node.getByteFrequencyData(frequencies);
      node.getByteTimeDomainData(waveform);
      window.dispatchEvent(new CustomEvent("echora:audio-waveform", { detail: waveform }));
      const binHz = context.sampleRate / node.fftSize;
      const bass = average(Math.floor(35 / binHz), Math.ceil(180 / binHz));
      const mid = average(Math.floor(180 / binHz), Math.ceil(2200 / binHz));
      const treble = average(Math.floor(2200 / binHz), Math.ceil(10000 / binHz));
      bassFloor += (bass - bassFloor) * .045;
      const onset = !player.paused && now - lastOnset > 220 && bass > Math.max(.16, bassFloor + .075);
      if (onset) lastOnset = now;
      window.dispatchEvent(new CustomEvent("echora:audio-reactivity", { detail: {
        bass, mid, treble, onset, timestamp: now / 1000,
        level: bass * .45 + mid * .4 + treble * .15,
        bassAttack: Math.max(0, bass - lastBass),
        midAttack: Math.max(0, mid - lastMid),
        trebleAttack: Math.max(0, treble - lastTreble),
      } }));
      lastBass = bass; lastMid = mid; lastTreble = treble;
      window.dispatchEvent(new CustomEvent("echora:playback-time", { detail: player.currentTime || 0 }));
    };
    context.resume(); analyze();
  }

  function loadLyrics(next: PlayerTrack) {
    const cached = lyricsCacheRef.current.get(next.id);
    if (cached) { setLyrics(cached); setLyricsLoading(false); return; }
    setLyrics(null); setLyricsLoading(true);
    if (lyricsRequestsRef.current.has(next.id)) return;
    lyricsRequestsRef.current.add(next.id);
    fetch(`/analysis/library/tracks/${next.id}/lyrics`).then(response => response.ok ? response.json() : null).then(value => {
      const resolved: PlayerLyrics = value ? { ...value, trackId: next.id } : { trackId: next.id, available: false };
      lyricsCacheRef.current.set(next.id, resolved);
      if (trackRef.current?.id === next.id) { setLyrics(resolved); setLyricsLoading(false); }
    }).catch(() => {
      const resolved: PlayerLyrics = { trackId: next.id, available: false };
      lyricsCacheRef.current.set(next.id, resolved);
      if (trackRef.current?.id === next.id) { setLyrics(resolved); setLyricsLoading(false); }
    }).finally(() => lyricsRequestsRef.current.delete(next.id));
  }

  function load(next: PlayerTrack) {
    const player = audio.current; if (!player) return;
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
  function next() { if (queueIndexRef.current < queueRef.current.length - 1) activateQueueIndex(queueIndexRef.current + 1); }
  function previous() {
    const player = audio.current; if (!player) return;
    if (player.currentTime > 4 || queueIndexRef.current <= 0) { seek(0); return; }
    activateQueueIndex(queueIndexRef.current - 1);
  }
  function clearQueue() { queueRef.current = track ? [track] : []; queueIndexRef.current = track ? 0 : -1; setQueue(queueRef.current); setQueueIndex(queueIndexRef.current); }
  function toggle() { const player = audio.current; if (!player || !track) return; startAnalysis(); if (player.paused) player.play(); else player.pause(); }
  function seek(seconds: number) { const player = audio.current; if (!player || !Number.isFinite(seconds)) return; player.currentTime = seconds; setCurrentTime(seconds); publishMediaPosition(player, trackRef.current?.durationSeconds); }
  function toggleMute() { const player = audio.current; if (!player) return; player.muted = !player.muted; setMuted(player.muted); }

  return <PlayerContext.Provider value={{ track, audioQuality, lyrics, lyricsLoading, playing, buffering, currentTime, duration, buffered, muted, expanded, queue, queueIndex, play, playQueue, next, previous, clearQueue, toggle, seek, toggleMute, setExpanded }}>{children}{expanded && track && <FullscreenPlayer />}</PlayerContext.Provider>;
}

export function usePlayer() {
  const value = useContext(PlayerContext);
  if (!value) throw new Error("usePlayer must be used inside PlayerProvider");
  return value;
}
