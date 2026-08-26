"use client";

import { createContext, ReactNode, useContext, useEffect, useRef, useState } from "react";
import FullscreenPlayer from "./FullscreenPlayer";
import { readPlaybackPreferences, streamUrlForQuality } from "./playbackPreferences";

export type PlayerTrack = { id: string; title: string; artist?: string; album?: string; durationSeconds?: number; streamUrl: string; coverUrl?: string };
export type AudioQuality = { codec?: string; content_type?: string; bit_rate_kbps?: number; bit_depth?: number; sample_rate_hz?: number; channels?: number; lossless?: boolean; streamQuality: "original" | "320" | "120" };
type PlayerState = {
  track: PlayerTrack | null; audioQuality: AudioQuality | null; playing: boolean; buffering: boolean; currentTime: number; duration: number; buffered: number; muted: boolean; expanded: boolean;
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
  const queueIndexRef = useRef(-1);
  const activateQueueIndexRef = useRef<(index: number) => void>(() => {});
  const [track, setTrack] = useState<PlayerTrack | null>(null);
  const [audioQuality, setAudioQuality] = useState<AudioQuality | null>(null);
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
    const time = () => setCurrentTime(player.currentTime || 0);
    const metadata = () => {
      const canonical = trackRef.current?.durationSeconds;
      setDuration(current => canonical && canonical > 0 ? canonical : Number.isFinite(player.duration) && player.duration > 0 ? player.duration : current);
    };
    const progress = () => setBuffered(player.buffered.length ? player.buffered.end(player.buffered.length - 1) : 0);
    const ended = () => { publishPalette(null); if (queueIndexRef.current >= 0 && queueIndexRef.current < queueRef.current.length - 1) activateQueueIndexRef.current(queueIndexRef.current + 1); else setPlaying(false); };
    const paused = () => { setPlaying(false); publishPalette(null); };
    const waiting = () => setBuffering(true);
    const ready = () => setBuffering(false);
    const started = () => { setPlaying(true); setBuffering(false); publishPalette(paletteRef.current); };
    player.addEventListener("timeupdate", time); player.addEventListener("durationchange", metadata);
    player.addEventListener("loadedmetadata", metadata); player.addEventListener("progress", progress); player.addEventListener("ended", ended);
    player.addEventListener("pause", paused); player.addEventListener("play", started);
    player.addEventListener("loadstart", waiting); player.addEventListener("waiting", waiting);
    player.addEventListener("canplay", ready); player.addEventListener("playing", ready);
    return () => { player.pause(); publishPalette(null); cancelAnimationFrame(analysisFrame.current); audioContext.current?.close(); player.remove(); };
  }, []);

  function startAnalysis() {
    const player = audio.current;
    if (!player || analyser.current) { audioContext.current?.resume(); return; }
    const browser = window as Window & { webkitAudioContext?: typeof AudioContext };
    const Context = window.AudioContext || browser.webkitAudioContext;
    if (!Context) return;
    const context = new Context();
    const node = context.createAnalyser();
    node.fftSize = 1024; node.smoothingTimeConstant = 0.8;
    const source = context.createMediaElementSource(player);
    source.connect(node); node.connect(context.destination);
    audioContext.current = context; analyser.current = node;
    const frequencies = new Uint8Array(node.frequencyBinCount);
    const average = (from: number, to: number) => {
      let sum = 0; const end = Math.min(to, frequencies.length);
      for (let index = from; index < end; index++) sum += frequencies[index];
      return end > from ? sum / (end - from) / 255 : 0;
    };
    const analyze = () => {
      node.getByteFrequencyData(frequencies);
      const binHz = context.sampleRate / node.fftSize;
      const bass = average(Math.floor(35 / binHz), Math.ceil(180 / binHz));
      const mid = average(Math.floor(180 / binHz), Math.ceil(2200 / binHz));
      const treble = average(Math.floor(2200 / binHz), Math.ceil(10000 / binHz));
      window.dispatchEvent(new CustomEvent("echora:audio-reactivity", { detail: { bass, mid, treble, level: bass * .45 + mid * .4 + treble * .15 } }));
      window.dispatchEvent(new CustomEvent("echora:playback-time", { detail: player.currentTime || 0 }));
      analysisFrame.current = requestAnimationFrame(analyze);
    };
    context.resume(); analyze();
  }

  function load(next: PlayerTrack) {
    const player = audio.current; if (!player) return;
    paletteRef.current = null; paletteTrackRef.current = next.id; trackRef.current = next; setBuffered(0); setBuffering(true); publishPalette(null);
    if (next.coverUrl) artworkPalette(next.coverUrl).then(palette => {
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
  function seek(seconds: number) { const player = audio.current; if (!player || !Number.isFinite(seconds)) return; player.currentTime = seconds; setCurrentTime(seconds); }
  function toggleMute() { const player = audio.current; if (!player) return; player.muted = !player.muted; setMuted(player.muted); }

  return <PlayerContext.Provider value={{ track, audioQuality, playing, buffering, currentTime, duration, buffered, muted, expanded, queue, queueIndex, play, playQueue, next, previous, clearQueue, toggle, seek, toggleMute, setExpanded }}>{children}{expanded && track && <FullscreenPlayer />}</PlayerContext.Provider>;
}

export function usePlayer() {
  const value = useContext(PlayerContext);
  if (!value) throw new Error("usePlayer must be used inside PlayerProvider");
  return value;
}
