"use client";

import { createContext, ReactNode, useContext, useEffect, useRef, useState } from "react";
import FullscreenPlayer from "./FullscreenPlayer";
import { readPlaybackPreferences, streamUrlForQuality } from "./playbackPreferences";

export type PlayerTrack = { id: string; title: string; artist?: string; album?: string; durationSeconds?: number; streamUrl: string; coverUrl?: string };
type PlayerState = {
  track: PlayerTrack | null; playing: boolean; buffering: boolean; currentTime: number; duration: number; buffered: number; muted: boolean; expanded: boolean;
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
  const canvas = document.createElement("canvas"); canvas.width = 24; canvas.height = 24;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) throw new Error("Canvas is unavailable");
  context.drawImage(image, 0, 0, 24, 24);
  const pixels = context.getImageData(0, 0, 24, 24).data;
  const colors: [number, number, number][] = [];
  for (let index = 0; index < pixels.length; index += 16) {
    if (pixels[index + 3] < 180) continue;
    const color: [number, number, number] = [pixels[index], pixels[index + 1], pixels[index + 2]];
    const high = Math.max(...color), low = Math.min(...color);
    if (high > 24 && low < 238) colors.push(color);
  }
  if (!colors.length) throw new Error("Artwork has no usable colors");
  const score = (color: [number, number, number]) => (Math.max(...color) - Math.min(...color)) * 1.4 + Math.max(...color) * .35;
  const accentSource = [...colors].sort((left, right) => score(right) - score(left))[0];
  const accent: [number, number, number] = accentSource.map(value => Math.round(105 + value * .58)) as [number, number, number];
  const average = colors.reduce((sum, color) => sum.map((value, channel) => value + color[channel]) as [number, number, number], [0, 0, 0]);
  const background = average.map(value => Math.round(value / colors.length * .22 + 4)) as [number, number, number];
  const distinct = [...colors].sort((left, right) => {
    const distance = (color: [number, number, number]) => color.reduce((sum, value, channel) => sum + Math.abs(value - accentSource[channel]), 0);
    return distance(right) - distance(left);
  })[0];
  const normalized = (color: [number, number, number]) => color.map(value => Math.min(1, Math.max(.15, value / 255))) as [number, number, number];
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
    startAnalysis(); player.src = streamUrlForQuality(next.streamUrl, readPlaybackPreferences().quality); setTrack(next); setCurrentTime(0); setDuration(next.durationSeconds || 0);
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

  return <PlayerContext.Provider value={{ track, playing, buffering, currentTime, duration, buffered, muted, expanded, queue, queueIndex, play, playQueue, next, previous, clearQueue, toggle, seek, toggleMute, setExpanded }}>{children}{expanded && track && <FullscreenPlayer />}</PlayerContext.Provider>;
}

export function usePlayer() {
  const value = useContext(PlayerContext);
  if (!value) throw new Error("usePlayer must be used inside PlayerProvider");
  return value;
}
