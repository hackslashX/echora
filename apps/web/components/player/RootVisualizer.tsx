"use client";

import { useEffect, useRef } from "react";
import { PlaybackPreferences, readPlaybackPreferences } from "./playbackPreferences";
import styles from "./RootVisualizer.module.css";

type Color = [number, number, number];
type Segment = { x1: number; y1: number; x2: number; y2: number; bucket: number; life: number; generation: number; width: number };
type Tip = { x: number; y: number; angle: number; bucket: number; energy: number; dormant: boolean; generation: number };
type PaletteEvent = { active: boolean; palette: { waves: [Color, Color, Color] } | null };

const BUCKETS = 24;
const MAX_SEGMENTS = 2200;
const fallback: [Color, Color, Color] = [[0.23, 0.78, 0.72], [0.48, 0.35, 0.72], [0.84, 0.43, 0.5]];
const mix = (left: Color, right: Color, amount: number): Color => left.map((value, index) => value + (right[index] - value) * amount) as Color;

export default function RootVisualizer() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    let width = 1, height = 1, frame = 0, generation = 0, lastFrame = 0;
    let preferences = readPlaybackPreferences();
    let enabled = preferences.wavesEnabled && preferences.backdropPreset === "roots";
    let palette = fallback;
    let levels = new Float32Array(BUCKETS);
    const previous = new Float32Array(BUCKETS);
    const segments: Segment[] = [];
    const tips: Tip[] = [];

    const seed = (bucket: number, parent?: Segment) => {
      const edgeBias = Math.random();
      const x = parent ? parent.x2 : edgeBias < .55 ? Math.random() * width : (Math.random() < .5 ? 0 : width);
      const y = parent ? parent.y2 : Math.random() * height;
      const angle = parent ? Math.atan2(parent.y2 - parent.y1, parent.x2 - parent.x1) + (Math.random() - .5) * 1.7 : Math.random() * Math.PI * 2;
      tips.push({ x, y, angle, bucket, energy: .2, dormant: false, generation });
    };

    const resize = () => {
      const bounds = canvas.getBoundingClientRect();
      const scale = Math.min(2, window.devicePixelRatio || 1);
      width = Math.max(1, Math.round(bounds.width * scale));
      height = Math.max(1, Math.round(bounds.height * scale));
      if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
      if (!tips.length) for (let bucket = 0; bucket < BUCKETS; bucket += 1) seed(bucket);
    };

    const receiveSpectrum = (event: Event) => {
      const bins = (event as CustomEvent<Uint8Array>).detail;
      const next = new Float32Array(BUCKETS);
      for (let bucket = 0; bucket < BUCKETS; bucket += 1) {
        const from = Math.max(1, Math.floor(Math.pow(bucket / BUCKETS, 2.15) * bins.length));
        const to = Math.max(from + 1, Math.floor(Math.pow((bucket + 1) / BUCKETS, 2.15) * bins.length));
        let sum = 0;
        for (let index = from; index < Math.min(to, bins.length); index += 1) sum += bins[index];
        const response = bucket < 8 ? preferences.bassReactivity : bucket < 17 ? preferences.vocalReactivity : preferences.trebleReactivity;
        next[bucket] = Math.min(1, sum / Math.max(1, Math.min(to, bins.length) - from) / 255 * response);
      }
      levels = next;
    };
    const receivePalette = (event: Event) => {
      const detail = (event as CustomEvent<PaletteEvent>).detail;
      if (detail.palette) palette = detail.palette.waves;
    };
    const changeTrack = () => { generation += 1; };
    const receivePreferences = (event: Event) => {
      preferences = (event as CustomEvent<PlaybackPreferences>).detail;
      enabled = preferences.wavesEnabled && preferences.backdropPreset === "roots";
      canvas.style.opacity = enabled ? "1" : "0";
    };
    canvas.style.opacity = enabled ? "1" : "0";

    const draw = (now: number) => {
      frame = requestAnimationFrame(draw);
      const frameInterval = preferences.waveFrameRate === "uncapped" ? 0 : 1000 / Number(preferences.waveFrameRate);
      if (!enabled || now - lastFrame < frameInterval) return;
      lastFrame = now;
      context.clearRect(0, 0, width, height);
      context.lineCap = "round";
      context.lineJoin = "round";

      for (const segment of segments) {
        if (segment.generation < generation) segment.life -= .006;
        else segment.life -= .0005;
      }
      while (segments.length && (segments[0].life <= 0 || segments.length > MAX_SEGMENTS)) segments.shift();

      const animationScale = preferences.animationSpeed === "slow" ? .65 : preferences.animationSpeed === "fast" ? 1.45 : 1;
      const pixelScale = Math.min(2, window.devicePixelRatio || 1);
      // Draw: live amplitude drives brightness and thickness so the whole root system breathes with the track.
      for (let bucket = 0; bucket < BUCKETS; bucket += 1) {
        const position = bucket / (BUCKETS - 1);
        const amplitude = levels[bucket];
        const base = position < .5 ? mix(palette[0], palette[1], position * 2) : mix(palette[1], palette[2], (position - .5) * 2);
        const rgb = `${Math.round(base[0] * 255)},${Math.round(base[1] * 255)},${Math.round(base[2] * 255)}`;
        for (const pass of [0, 1]) {
          context.strokeStyle = pass ? `rgba(${rgb},${.16 + amplitude * .55})` : `rgba(${rgb},${amplitude * .22})`;
          context.lineWidth = (pass ? 2.2 + amplitude * 4.5 : 9 + amplitude * 16) * pixelScale * .5;
          context.beginPath();
          for (const segment of segments) {
            if (segment.bucket !== bucket || segment.life <= 0) continue;
            context.moveTo(segment.x1, segment.y1); context.lineTo(segment.x2, segment.y2);
          }
          if (pass || amplitude > .08) context.stroke();
        }
      }

      for (let bucket = 0; bucket < BUCKETS; bucket += 1) {
        const amplitude = levels[bucket];
        const delta = amplitude - previous[bucket];
        const attack = Math.max(0, delta);
        const activeTips = tips.filter(tip => tip.bucket === bucket && tip.generation === generation && !tip.dormant);
        if ((amplitude > .1 || attack > .05) && !activeTips.length) {
          const candidates = segments.filter(segment => segment.bucket === bucket && segment.life > .25);
          seed(bucket, candidates[Math.floor(Math.random() * candidates.length)]);
        }
        for (const tip of activeTips) {
          if (amplitude < .05) { tip.energy *= .9; if (tip.energy < .04) tip.dormant = true; continue; }
          tip.energy += (amplitude - tip.energy) * .35;
          // Attacks kick the heading hard; sustained tone wanders gently.
          tip.angle += delta * 6 + (Math.random() - .5) * (.06 + amplitude * .22 + attack * 1.2);
          const speed = (.4 + Math.pow(amplitude, 1.4) * 14 + attack * 40) * animationScale * pixelScale;
          let x = tip.x + Math.cos(tip.angle) * speed;
          let y = tip.y + Math.sin(tip.angle) * speed;
          segments.push({ x1: tip.x, y1: tip.y, x2: x, y2: y, bucket, life: 1, generation, width: .45 + amplitude * 2.1 });
          // Wrap around the canvas so roots continue from the opposite edge without a stroke spanning the screen.
          if (x < 0) x += width; else if (x > width) x -= width;
          if (y < 0) y += height; else if (y > height) y -= height;
          tip.x = x; tip.y = y;
          if (Math.random() < amplitude * .03 + attack * .5) seed(bucket, segments[segments.length - 1]);
        }
        previous[bucket] = amplitude;
      }
      if (tips.length > BUCKETS * 6) tips.splice(0, tips.length - BUCKETS * 6);
    };

    resize();
    window.addEventListener("resize", resize);
    window.addEventListener("echora:audio-spectrum", receiveSpectrum);
    window.addEventListener("echora:track-palette", receivePalette);
    window.addEventListener("echora:track-change", changeTrack);
    window.addEventListener("echora:playback-preferences", receivePreferences);
    frame = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", resize);
      window.removeEventListener("echora:audio-spectrum", receiveSpectrum);
      window.removeEventListener("echora:track-palette", receivePalette);
      window.removeEventListener("echora:track-change", changeTrack);
      window.removeEventListener("echora:playback-preferences", receivePreferences);
    };
  }, []);

  return <canvas ref={canvasRef} className={styles.roots} aria-hidden="true" />;
}
