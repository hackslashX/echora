/**
 * Backdrop presets inspired by the Void audio visualizer (https://github.com/epxweb/void-visualizer)
 * by epxstudio (taniguchi@epxstudio.com), licensed under the GNU General Public License.
 * Concepts adapted under GPL: the "Void tunnel", "Digital curtain", and "ASCII dance"
 * presets are reimplementations of their scenes (InfiniteTunnel, DigitalCurtain,
 * ASCIIDance) on Echora's 2D canvas pipeline, with Echora palette, tempo,
 * waveform-history, and curvature extensions.
 */

"use client";

import { useEffect, useRef } from "react";
import { BackdropPreset, PlaybackPreferences, readPlaybackPreferences } from "../player/playbackPreferences";
import styles from "./Backdrop.module.css";

type RenderLayer = { render: (time: number) => void };
type Color = [number, number, number];
type SplineSettings = { flowSpeed: number; bandAmplitude: number; waveHeightScale: number; brightness: number; opacity: number; layerAmplitudes: number[]; layerColors: Color[]; colorR: number; colorG: number; colorB: number };
type ParticleSettings = { count: number; flowSpeed: number; opacity: number; sizeBase: number; sizeVar: number };
type Reactivity = { bass: number; mid: number; treble: number; level: number; onset?: boolean; timestamp?: number; bassAttack?: number; midAttack?: number; trebleAttack?: number };
type TunnelState = { angle: number; offset: number; speed: number; bendX: number; bendY: number; lastOnset: number; intervals: number[]; impulseX: number; impulseY: number; bassFlash: number; trebleFlash: number };
type XmbWindow = Window & {
  createSplineLayer?: (gl: WebGL2RenderingContext, canvas: HTMLCanvasElement) => RenderLayer;
  createParticlesLayer?: (gl: WebGL2RenderingContext, canvas: HTMLCanvasElement) => RenderLayer;
  SPLINE_SETTINGS?: SplineSettings;
  PARTICLE_SETTINGS?: ParticleSettings;
};

const scripts = ["spline-settings.js", "particles-settings.js", "spline-reverse.js", "spline.js", "particles.js"];
const scriptLoads = new Map<string, Promise<void>>();

function loadScript(file: string) {
  const existing = scriptLoads.get(file);
  if (existing) return existing;
  const promise = new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = `/vendor/ps3-xmb/${file}`;
    script.async = false;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`Could not load ${file}`));
    document.head.appendChild(script);
  });
  scriptLoads.set(file, promise);
  return promise;
}

const POINTS = 72;
const TUNNEL_RINGS = 26;
const RING_SPACING = 1.05;
const DEFAULT_BASE: Color = [37, 89, 179];
const DEFAULT_WAVES: [Color, Color, Color] = [[0.48, 0.98, 0.92], [0.76, 0.66, 1], [0.55, 0.8, 1]];

function sceneBackground(ctx: CanvasRenderingContext2D, base: Color, width: number, height: number) {
  const gradient = ctx.createLinearGradient(0, 0, 0, height);
  const top = base.map((value, channel) => value * (channel === 2 ? 0.09 * 1.2 : 0.09));
  const bottom = base.map(value => value * 0.62);
  gradient.addColorStop(0, `rgb(${top.map(value => Math.round(value)).join(",")})`);
  gradient.addColorStop(1, `rgb(${bottom.map(value => Math.round(value)).join(",")})`);
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);
}


type CurtainCell = { digit: number; lastChange: number; changeSpeed: number; speedMult: number; flash: number; darken: number };
type CurtainState = { cells: CurtainCell[]; cols: number; rows: number };
const SEGMENT_MAP: Record<number, number[]> = {
  0: [1, 1, 1, 1, 1, 1, 0], 1: [0, 1, 1, 0, 0, 0, 0], 2: [1, 1, 0, 1, 1, 0, 1], 3: [1, 1, 1, 1, 0, 0, 1],
  4: [0, 1, 1, 0, 0, 1, 1], 5: [1, 0, 1, 1, 0, 1, 1], 6: [1, 0, 1, 1, 1, 1, 1], 7: [1, 1, 1, 0, 0, 0, 0],
  8: [1, 1, 1, 1, 1, 1, 1], 9: [1, 1, 1, 1, 0, 1, 1],
};
const ASCII_CHARS = "♪♫★☆◆◇○●◐◑░▒▓█▪▫ABCDEФ0123456789!?#$%&<>*+=-~";
let asciiAtlas: HTMLCanvasElement | null = null;
let asciiRandoms: Float32Array | null = null;

function asciiAtlasCanvas(): HTMLCanvasElement {
  if (asciiAtlas) return asciiAtlas;
  const canvas = document.createElement("canvas");
  canvas.width = 256; canvas.height = 256;
  const ctx = canvas.getContext("2d")!;
  ctx.fillStyle = "#fff";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  for (let index = 0; index < 64; index++) {
    ctx.font = `${index % 2 ? 300 : 500} ${36 + (index % 3) * 4}px "DM Mono", monospace`;
    ctx.fillText(ASCII_CHARS[index % ASCII_CHARS.length], (index % 8) * 32 + 16, Math.floor(index / 8) * 32 + 17);
  }
  asciiAtlas = canvas;
  return canvas;
}

function curtainCellsFor(cols: number, rows: number, elapsed: number, existing: CurtainState | null): CurtainState {
  if (existing && existing.cols === cols && existing.rows === rows) return existing;
  const cells: CurtainCell[] = Array.from({ length: cols * rows }, () => ({
    digit: Math.floor(Math.random() * 10),
    lastChange: elapsed,
    changeSpeed: 0.1 + Math.random() * 0.5,
    speedMult: 1,
    flash: 0,
    darken: 1,
  }));
  return { cells, cols, rows };
}

function presetScene(ctx: CanvasRenderingContext2D, preset: BackdropPreset, width: number, height: number, elapsed: number, clock: number, delta: number, reactive: Reactivity, background: Color, waves: [Color, Color, Color], envelope: Float32Array | null, waveHistory: Float32Array[], tunnel: TunnelState, curtainState: { current: CurtainState | null }) {
  const mix = (a: Color, b: Color, amount: number): Color => [a[0] + (b[0] - a[0]) * amount, a[1] + (b[1] - a[1]) * amount, a[2] + (b[2] - a[2]) * amount];
  const css = (color: Color, alpha = 1) => `rgba(${color.map(value => Math.round(value * 255)).join(",")},${alpha})`;
  sceneBackground(ctx, background, width, height);
  const dpr = Math.max(0.01, width / Math.max(1, window.innerWidth));
  ctx.save();
  ctx.scale(dpr, dpr);
  const w = width / dpr;
  const h = height / dpr;

  if (preset === "oscilloscope") {
    const midline = h * 0.5;
    const points = envelope ?? new Float32Array(POINTS);
    const amplitude = h * 0.3 * (0.5 + reactive.level * 1.35);
    const value = (t: number) => {
      const folded = t < 0.5 ? t * 2 : (1 - t) * 2;
      const position = Math.min(POINTS - 1.001, Math.max(0, folded * (POINTS - 1)));
      const index = Math.floor(position);
      const fraction = position - index;
      const smooth = fraction * fraction * (3 - 2 * fraction);
      return points[index] * (1 - smooth) + points[index + 1] * smooth;
    };
    const edge: [number, number][] = [];
    for (let x = 0; x <= w; x += 3) {
      const t = x / w;
      const magnitude = value(t) * amplitude * Math.pow(Math.max(0, Math.sin(Math.PI * Math.min(1, t * 1.06))), 0.6);
      edge.push([x, midline - magnitude]);
    }
    const gradient = ctx.createLinearGradient(0, midline - amplitude, 0, midline + amplitude);
    gradient.addColorStop(0, css(waves[2], 0.05));
    gradient.addColorStop(0.5, css(waves[1], 0.3));
    gradient.addColorStop(1, css(waves[0], 0.05));
    ctx.beginPath();
    edge.forEach(([x, y], index) => { if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y); });
    for (let index = edge.length - 1; index >= 0; index--) {
      const [x, y] = edge[index];
      ctx.lineTo(x, midline + (midline - y) * 0.82);
    }
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();
    ctx.shadowColor = css(waves[1], 0.5);
    ctx.shadowBlur = 24;
    ctx.strokeStyle = css(waves[1], 0.85);
    ctx.lineWidth = 2.2;
    ctx.beginPath();
    edge.forEach(([x, y], index) => { if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y); });
    ctx.stroke();
    ctx.shadowBlur = 0;
    ctx.strokeStyle = css(waves[0], 0.3);
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    edge.forEach(([x, y], index) => { if (index === 0) ctx.moveTo(x, midline + (midline - y) * 0.82); else ctx.lineTo(x, midline + (midline - y) * 0.82); });
    ctx.stroke();
  } else if (preset === "void") {
    const cx = w / 2;
    const cy = h * 0.5;
    const focal = h * 0.62;
    const farZ = TUNNEL_RINGS * RING_SPACING;
    const bass = reactive.bass;
    const mid = reactive.mid;
    const treble = reactive.treble;

    const decayFactor = Math.exp(-delta * 6);
    tunnel.bassFlash = Math.max((reactive.bassAttack ?? 0) * 1.6, tunnel.bassFlash * decayFactor);
    tunnel.trebleFlash = Math.max((reactive.trebleAttack ?? 0) * 1.5, tunnel.trebleFlash * decayFactor);
    if (reactive.onset && reactive.timestamp && reactive.timestamp > tunnel.lastOnset) {
      if (tunnel.lastOnset >= 0) {
        let interval = reactive.timestamp - tunnel.lastOnset;
        if (interval >= 0.25 && interval <= 2) {
          while (interval < 0.43) interval *= 2;
          while (interval > 0.86) interval /= 2;
          tunnel.intervals.push(interval);
          if (tunnel.intervals.length > 8) tunnel.intervals.shift();
        }
      }
      tunnel.lastOnset = reactive.timestamp;
      tunnel.impulseX = Math.max(-1.25, Math.min(1.25, tunnel.impulseX + (Math.random() * 2 - 1) * 0.72));
      tunnel.impulseY = Math.max(-1.25, Math.min(1.25, tunnel.impulseY + (Math.random() * 2 - 1) * 0.58));
    }
    if (tunnel.lastOnset >= 0 && clock - tunnel.lastOnset > 2.5) tunnel.intervals.length = 0;
    const sortedIntervals = [...tunnel.intervals].sort((a, b) => a - b);
    const tempoInterval = sortedIntervals.length ? sortedIntervals[Math.floor(sortedIntervals.length / 2)] : 0;
    const bpm = tempoInterval ? 60 / tempoInterval : 0;
    const tempoSpeed = bpm ? Math.max(0.28, Math.min(1.05, (bpm - 45) / 95)) : 0;
    const targetSpeed = Math.max(0.16, 0.2 + mid * 1.35 + tempoSpeed * 0.95);
    tunnel.speed += (targetSpeed - tunnel.speed) * Math.min(1, delta * 1.8);
    tunnel.angle += tunnel.speed * delta * 0.42;
    tunnel.offset = (tunnel.offset + tunnel.speed * delta) % RING_SPACING;

    const wanderX = Math.sin(clock * 0.049 + 2.3) * 0.62 + Math.sin(clock * 0.021 + 0.7) * 0.38;
    const wanderY = Math.sin(clock * 0.037 + 4.1) * 0.58 + Math.sin(clock * 0.017 + 1.9) * 0.42;
    const decay = Math.exp(-delta * 0.35);
    tunnel.impulseX *= decay;
    tunnel.impulseY *= decay;
    const targetX = Math.max(-1.35, Math.min(1.35, wanderX + tunnel.impulseX)) * w * 0.13 * (0.55 + reactive.level * 0.9);
    const targetY = Math.max(-1.35, Math.min(1.35, wanderY + tunnel.impulseY)) * h * 0.11 * (0.55 + reactive.level * 0.9);
    tunnel.bendX += (targetX - tunnel.bendX) * Math.min(1, delta * 0.75);
    tunnel.bendY += (targetY - tunnel.bendY) * Math.min(1, delta * 0.75);

    const centerline = (reach: number) => {
      const crossX = -tunnel.bendY * 0.2;
      const crossY = tunnel.bendX * 0.12;
      const one = 1 - reach;
      const x = 3 * one * one * reach * crossX + 3 * one * reach * reach * (tunnel.bendX * 0.58 + crossX) + reach * reach * reach * tunnel.bendX;
      const y = 3 * one * one * reach * crossY + 3 * one * reach * reach * (tunnel.bendY * 0.58 + crossY) + reach * reach * reach * tunnel.bendY;
      const dx = 3 * one * one * crossX + 6 * one * reach * (tunnel.bendX * 0.58) + 3 * reach * reach * (tunnel.bendX * 0.42 - crossX);
      const dy = 3 * one * one * crossY + 6 * one * reach * (tunnel.bendY * 0.58) + 3 * reach * reach * (tunnel.bendY * 0.42 - crossY);
      return { x: cx + x, y: cy + y, dx, dy };
    };

    const destination = centerline(1);
    const depth = ctx.createRadialGradient(destination.x, destination.y, 0, destination.x, destination.y, Math.min(w, h) * 0.75);
    depth.addColorStop(0, css(mix(waves[1], [0, 0, 0], 0.72), 0.5 + bass * 0.22));
    depth.addColorStop(0.35, css(mix(waves[0], [0, 0, 0], 0.86), 0.2));
    depth.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = depth;
    ctx.fillRect(0, 0, w, h);

    const rings = Array.from({ length: TUNNEL_RINGS }, (_, index) => {
      let z = index * RING_SPACING + 0.55 - tunnel.offset;
      if (z < 0.45) z += farZ;
      return { z, index };
    }).sort((left, right) => right.z - left.z);
    type Joint = [number, number];
    type Strut = { start: Joint; end: Joint; alpha: number; phase: number };
    const struts: Strut[] = [];
    let previous: { joints: Joint[]; alpha: number; index: number } | null = null;
    ctx.globalCompositeOperation = "lighter";
    for (const ring of rings) {
      const reach = ring.z / farZ;
      const path = centerline(reach);
      const radius = 1.55 * focal / ring.z;
      const fadeIn = Math.min(1, Math.max(0, (farZ - ring.z) / (RING_SPACING * 2.5)));
      const fadeOut = Math.min(1, Math.max(0, (ring.z - 0.45) / 0.6));
      const alpha = Math.min(1, 1.25 / (1 + ring.z * 0.11)) * fadeIn * fadeOut;
      if (alpha < 0.03 || radius > Math.max(w, h) * 1.6 || radius < 14) { previous = null; continue; }
      const tangentStrength = Math.min(0.28, Math.hypot(path.dx / w, path.dy / h) * 1.8);
      const squash = 1 - tangentStrength;
      const orientation = Math.atan2(path.dy, path.dx) * 0.32;
      const cosOrientation = Math.cos(orientation);
      const sinOrientation = Math.sin(orientation);
      tunnel.angle += treble * delta * 0.35;
      const rotation = tunnel.angle + ring.z * 0.045;
      const historyIndex = Math.min(waveHistory.length - 1, Math.max(0, Math.floor((1 - reach) * Math.max(0, waveHistory.length - 1))));
      const shape = waveHistory[historyIndex] ?? envelope ?? new Float32Array(POINTS);
      const ringPoint = (angle: number): Joint => {
        const wrapped = ((angle - rotation) / (Math.PI * 2) % 1 + 1) % 1;
        const position = wrapped * (POINTS - 1);
        const low = Math.floor(position);
        const blend = position - low;
        const sample = shape[low] * (1 - blend) + shape[Math.min(POINTS - 1, low + 1)] * blend;
        const bassShape = Math.sin((angle - rotation) * 2 + ring.z * .12) * bass * .032;
        const modulated = radius * (1 + sample * (.03 + bass * .045) + bassShape) * (1 + bass * .06 + tunnel.bassFlash * .12);
        const localX = Math.cos(angle) * modulated * squash;
        const localY = Math.sin(angle) * modulated;
        return [path.x + localX * cosOrientation - localY * sinOrientation, path.y + localX * sinOrientation + localY * cosOrientation];
      };
      const panels = 10;
      const panelArc = Math.PI * 2 / panels;
      const gap = 0.16;
      ctx.lineWidth = Math.max(0.8, radius * 0.016 * (1 + bass * .75));
      const ringOpacity = Math.min(.9, .32 + alpha * .62 + bass * .16 + mid * .1) * fadeIn * fadeOut;
      ctx.strokeStyle = css(waves[1], Math.min(.95, ringOpacity + tunnel.bassFlash * .3));
      for (let panel = 0; panel < panels; panel++) {
        const start = rotation + panel * panelArc + gap / 2;
        ctx.beginPath();
        for (let point = 0; point <= 8; point++) {
          const projected = ringPoint(start + point / 8 * (panelArc - gap));
          if (point === 0) ctx.moveTo(projected[0], projected[1]); else ctx.lineTo(projected[0], projected[1]);
        }
        ctx.stroke();
      }
      const joints = Array.from({ length: panels }, (_, joint) => ringPoint(rotation + joint * panelArc));
      if (previous) {
        for (let joint = 0; joint < panels; joint++) struts.push({ start: previous.joints[joint], end: joints[joint], alpha: Math.min(previous.alpha, alpha) * 0.6, phase: previous.index * panels + joint });
      }
      if (treble + tunnel.trebleFlash > 0.05 && fadeIn > 0.5) {
        ctx.fillStyle = css(waves[2], Math.min(0.9, (treble + tunnel.trebleFlash) * 1.3 * alpha));
        for (const [jx, jy] of joints) { ctx.beginPath(); ctx.arc(jx, jy, Math.max(0.8, radius * 0.012), 0, Math.PI * 2); ctx.fill(); }
      }
      previous = { joints, alpha, index: ring.index };
    }
    ctx.lineWidth = 1;
    for (const strut of struts) {
      const dx = strut.end[0] - strut.start[0];
      const dy = strut.end[1] - strut.start[1];
      const length = Math.hypot(dx, dy) || 1;
      const displacement = Math.max(-12, Math.min(12, Math.sin(clock * 6.5 + strut.phase * 0.73) * (treble * 9 + tunnel.trebleFlash * 26)));
      const controlX = (strut.start[0] + strut.end[0]) / 2 - dy / length * displacement;
      const controlY = (strut.start[1] + strut.end[1]) / 2 + dx / length * displacement;
      ctx.strokeStyle = css(waves[0], strut.alpha);
      ctx.beginPath(); ctx.moveTo(strut.start[0], strut.start[1]); ctx.quadraticCurveTo(controlX, controlY, strut.end[0], strut.end[1]); ctx.stroke();
    }
    ctx.globalCompositeOperation = "source-over";
  } else if (preset === "curtain") {
    const bass = reactive.bass;
    const mid = reactive.mid;
    const treble = reactive.treble;
    const cols = Math.max(10, Math.min(30, Math.floor(w / 62)));
    const rows = Math.max(5, Math.min(16, Math.floor(h / 74)));
    const state = curtainCellsFor(cols, rows, clock, curtainState.current);
    curtainState.current = state;
    const digitW = w / cols;
    const digitH = Math.min(digitW * 1.55, h / rows);
    const cellW = Math.min(digitW * 0.42, digitH * 0.34);
    const cellH = cellW * 1.18;
    const flashDecay = Math.exp(-delta * 6);
    if ((reactive.bassAttack ?? 0) > 0.05) {
      for (const cell of state.cells) if (Math.random() < 0.1) cell.flash = 1;
    }
    for (const cell of state.cells) {
      if (cell.speedMult === 1 && Math.random() < mid * delta * 9) cell.speedMult = 18 + Math.random() * 20;
      if (clock - cell.lastChange > 1 / (cell.changeSpeed * cell.speedMult)) {
        cell.digit = Math.floor(Math.random() * 10);
        cell.lastChange = clock;
        if (cell.speedMult > 1) cell.speedMult = 1;
      }
      if (Math.random() < treble * delta * 7) cell.darken = 0;
      if (cell.darken < 1) cell.darken = Math.min(1, cell.darken + delta * 0.7);
      cell.flash *= flashDecay;
      const visible = SEGMENT_MAP[cell.digit];
      const brightness = Math.min(1, 0.05 + bass * 0.3 + cell.flash * 1.1) * cell.darken;
      const cellIndex = state.cells.indexOf(cell);
      const x = (cellIndex % cols) * digitW + (digitW - cellW * 2) / 2;
      const y = Math.floor(cellIndex / cols) * digitH + (digitH - (cellH * 2 + cellW * 0.36)) / 2;
      const segmentColor = (alpha: number) => css(mix(waves[1], waves[0], 0.3), alpha);
      ctx.lineWidth = Math.max(1.5, cellH * 0.22);
      ctx.lineCap = "round";
      const draw = (x1: number, y1: number, x2: number, y2: number, on: boolean) => {
        ctx.strokeStyle = on ? segmentColor(brightness) : segmentColor(0.025 * cell.darken);
        ctx.beginPath(); ctx.moveTo(x + x1, y + y1); ctx.lineTo(x + x2, y + y2); ctx.stroke();
      };
      draw(cellW * .18, 0, cellW * 1.82, 0, !!visible[0]);
      draw(cellW * 2, cellH * .18, cellW * 2, cellH * .82, !!visible[1]);
      draw(cellW * 2, cellH * 1.18, cellW * 2, cellH * 1.82, !!visible[2]);
      draw(cellW * .18, cellH * 2, cellW * 1.82, cellH * 2, !!visible[3]);
      draw(0, cellH * 1.18, 0, cellH * 1.82, !!visible[4]);
      draw(0, cellH * .18, 0, cellH * .82, !!visible[5]);
      draw(cellW * .18, cellH, cellW * 1.82, cellH, !!visible[6]);
    }
  } else if (preset === "ascii") {
    const bass = reactive.bass;
    const mid = reactive.mid;
    const treble = reactive.treble;
    const atlas = asciiAtlasCanvas();
    const cell = Math.max(22, Math.min(30, Math.floor(w / 34)));
    const cols = Math.ceil(w / cell);
    const rows = Math.ceil(h / cell);
    if (!asciiRandoms || asciiRandoms.length < cols * rows) asciiRandoms = Float32Array.from({ length: cols * rows }, () => Math.random());
    const rand = asciiRandoms;
    const noiseSpeed = 0.02 + mid * 0.3;
    const slowTime = Math.floor(clock * 9);
    ctx.font = `${cell * 0.92}px "DM Mono", monospace`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    for (let row = 0; row < rows; row++) {
      for (let column = 0; column < cols; column++) {
        const gridIndex = row * cols + column;
        const px = (column + 0.5) * cell;
        const py = (row + 0.5) * cell;
        const nx = column / cols * 3;
        const ny = row / rows * 3;
        const noise = (
          Math.sin(nx * 3 + clock * noiseSpeed * 9) +
          Math.sin(ny * 4 + clock * noiseSpeed * 4.5) +
          Math.sin(nx * 5 - clock * noiseSpeed * 1.8) +
          Math.sin(ny * 7 - clock * noiseSpeed * 7.2)
        ) / 8 + 0.5;
        let charIndex = Math.floor((noise * 64 + rand[gridIndex] * 64 + slowTime * 7) % 64);
        if (rand[(gridIndex + slowTime) % rand.length] < treble * 0.3) charIndex = Math.floor(rand[(gridIndex * 7 + slowTime) % rand.length] * 64);
        const brightness = Math.max(0, Math.min(1, noise * 0.2 + bass * 0.4));
        if (brightness < 0.3) continue;
        const color = mix(waves[0], waves[1], noise);
        const edgeFade = Math.min(1, Math.sin(Math.PI * Math.min(1, (row + 0.5) / rows * 1.04)) * 0.7 + 0.3) * Math.min(1, Math.sin(Math.PI * Math.min(1, (column + 0.5) / cols * 1.04)) * 0.5 + 0.5);
        ctx.globalAlpha = Math.min(0.22, brightness * 0.3 * edgeFade);
        ctx.fillStyle = css(brightness > 0.85 ? waves[1] : color, 1);
        ctx.drawImage(atlas, (charIndex % 8) * 32, Math.floor(charIndex / 8) * 32, 32, 32, px - cell / 2, py - cell / 2, cell, cell);
      }
    }
    ctx.globalAlpha = 1;
  }
  ctx.restore();
}

export default function Backdrop() {
  const glRef = useRef<HTMLCanvasElement>(null);
  const sceneRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const maybeGlCanvas = glRef.current;
    const maybeSceneCanvas = sceneRef.current;
    if (!maybeGlCanvas || !maybeSceneCanvas) return;
    const canvas: HTMLCanvasElement = maybeGlCanvas;
    const sceneCanvas: HTMLCanvasElement = maybeSceneCanvas;
    const scene = sceneCanvas.getContext("2d");
    if (!scene) return;
    let cancelled = false;
    let animation = 0;
    let removeResize = () => {};
    const target: Reactivity = { bass: 0, mid: 0, treble: 0, level: 0 };
    let preferences = readPlaybackPreferences();
    let paletteTarget: { background: Color; waves: [Color, Color, Color] } | null = null;
    let waveform: Uint8Array | null = null;
    const envelope = new Float32Array(POINTS);
    const waveHistory: Float32Array[] = [];
    const curtainState: { current: CurtainState | null } = { current: null };
    const tunnelState: TunnelState = { angle: 0, offset: 0, speed: 0.22, bendX: 0, bendY: 0, lastOnset: -1, intervals: [], impulseX: 0, impulseY: 0, bassFlash: 0, trebleFlash: 0 };

    let opacityScale = 1;
    let targetOpacityScale = 1;
    const baseColor: Color = [...DEFAULT_BASE];
    const waveColors: [Color, Color, Color] = [[...DEFAULT_WAVES[0]], [...DEFAULT_WAVES[1]], [...DEFAULT_WAVES[2]]];
    const reactive: Reactivity = { ...target };
    const receiveAudio = (event: Event) => Object.assign(target, (event as CustomEvent<Reactivity>).detail);
    const receiveMode = (event: Event) => { targetOpacityScale = (event as CustomEvent<{ waveOpacity: number }>).detail.waveOpacity; };
    const receivePreferences = (event: Event) => { preferences = (event as CustomEvent<PlaybackPreferences>).detail; };
    const receivePalette = (event: Event) => {
      const detail = (event as CustomEvent<{ active: boolean; palette: { background: Color; waves: [Color, Color, Color] } | null }>).detail;
      paletteTarget = detail.active ? detail.palette : null;
    };
    const receiveWaveform = (event: Event) => {
      waveform = (event as CustomEvent<Uint8Array>).detail;
      const signed = new Float32Array(POINTS);
      for (let point = 0; point < POINTS; point++) {
        const start = Math.floor(point / POINTS * waveform.length);
        const end = Math.max(start + 1, Math.floor((point + 1) / POINTS * waveform.length));
        let sum = 0;
        for (let index = start; index < end; index++) sum += (waveform[index] - 128) / 128;
        signed[point] = sum / (end - start);
      }
      const smooth = new Float32Array(POINTS);
      const previous = waveHistory[0];
      for (let point = 0; point < POINTS; point++) {
        const spatial = (
          signed[(point + POINTS - 2) % POINTS] +
          signed[(point + POINTS - 1) % POINTS] * 2 +
          signed[point] * 3 +
          signed[(point + 1) % POINTS] * 2 +
          signed[(point + 2) % POINTS]
        ) / 9;
        smooth[point] = previous ? previous[point] * .7 + spatial * .3 : spatial;
      }
      waveHistory.unshift(smooth);
      if (waveHistory.length > 96) waveHistory.pop();
    };
    const resetTunnel = () => {
      tunnelState.speed = .22; tunnelState.lastOnset = -1; tunnelState.intervals.length = 0; tunnelState.bassFlash = 0; tunnelState.trebleFlash = 0;
      tunnelState.impulseX = 0; tunnelState.impulseY = 0; waveHistory.length = 0;
    };
    window.addEventListener("echora:audio-reactivity", receiveAudio);
    window.addEventListener("echora:backdrop-mode", receiveMode);
    window.addEventListener("echora:track-palette", receivePalette);
    window.addEventListener("echora:audio-waveform", receiveWaveform);
    window.addEventListener("echora:track-change", resetTunnel);
    window.addEventListener("echora:playback-preferences", receivePreferences);

    async function start() {
      for (const file of scripts) await loadScript(file);
      if (cancelled) return;
      const gl = canvas.getContext("webgl2", { antialias: true, alpha: false, powerPreference: "high-performance" });
      const scope = window as XmbWindow;
      if (!gl || !scope.createSplineLayer || !scope.createParticlesLayer) return;
      gl.getExtension("OES_texture_float_linear");
      gl.getExtension("EXT_color_buffer_float");

      const resize = () => {
        const ratio = Math.min(window.devicePixelRatio || 1, 2);
        for (const [element, elementRatio] of [[canvas, ratio], [sceneCanvas, 1]] as const) {
          const width = Math.max(1, Math.floor(element.clientWidth * elementRatio));
          const height = Math.max(1, Math.floor(element.clientHeight * elementRatio));
          if (element.width !== width || element.height !== height) {
            element.width = width; element.height = height;
          }
        }
        gl.viewport(0, 0, canvas.width, canvas.height);
      };
      window.addEventListener("resize", resize);
      removeResize = () => window.removeEventListener("resize", resize);
      resize();

      const spline = scope.createSplineLayer(gl, canvas);
      const particles = scope.createParticlesLayer(gl, canvas);
      const splineSettings = scope.SPLINE_SETTINGS;
      const particleSettings = scope.PARTICLE_SETTINGS;
      const baseline = splineSettings && particleSettings ? {
        spline: { layerAmplitudes: [...splineSettings.layerAmplitudes], opacity: splineSettings.opacity, layerColors: splineSettings.layerColors.map(color => [...color] as Color), background: [splineSettings.colorR, splineSettings.colorG, splineSettings.colorB] as Color },
        particles: { count: particleSettings.count },
      } : null;
      let previous = performance.now();
      let lastRendered = 0;
      let elapsed = 0;
      const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      const frame = (now: number) => {
        const activeFrameInterval = preferences.waveFrameRate === "uncapped" ? 0 : 1000 / Number(preferences.waveFrameRate);
        const frameInterval = preferences.wavesEnabled ? activeFrameInterval : 500;
        if (now - lastRendered < frameInterval) {
          if (!reduced && !cancelled) animation = requestAnimationFrame(frame);
          return;
        }
        const animationSpeed = preferences.animationSpeed === "slow" ? 0.65 : preferences.animationSpeed === "fast" ? 1.45 : 1;
        if (preferences.wavesEnabled) elapsed += Math.max(0, now - previous) / 1000 * animationSpeed;
        const frameDelta = Math.min(0.1, Math.max(0.001, (now - previous) / 1000));
        previous = now;
        lastRendered = now;
        for (const key of ["bass", "mid", "treble", "level"] as const) reactive[key] += (target[key] - reactive[key]) * .11;
        reactive.bassAttack = target.bassAttack ?? 0;
        reactive.midAttack = target.midAttack ?? 0;
        reactive.trebleAttack = target.trebleAttack ?? 0;
        reactive.onset = target.onset;
        reactive.timestamp = target.timestamp;
        target.onset = false;
        for (let point = 0; point < POINTS; point++) {
          let targetValue: number;
          if (waveform && waveform.length) {
            const start = Math.floor((point / POINTS) * (waveform.length - 1));
            const end = Math.floor(((point + 1) / POINTS) * (waveform.length - 1));
            let peak = 0;
            for (let index = start; index <= end; index++) peak = Math.max(peak, Math.abs(waveform[index] - 128));
            targetValue = Math.min(1, (peak / 128) * 1.5);
          } else {
            targetValue = 0.05 + 0.035 * (1 + Math.sin(elapsed * 1.15 + point * 0.45) * Math.sin(elapsed * 0.53 + point * 0.21));
          }
          envelope[point] += (targetValue - envelope[point]) * (targetValue > envelope[point] ? 0.5 : 0.12);
        }
        opacityScale += (targetOpacityScale - opacityScale) * .035;
        const background = paletteTarget?.background ?? DEFAULT_BASE;
        const colors = paletteTarget?.waves ?? DEFAULT_WAVES;
        for (let channel = 0; channel < 3; channel++) baseColor[channel] += (background[channel] - baseColor[channel]) * .025;
        for (let layer = 0; layer < 3; layer++) {
          for (let channel = 0; channel < 3; channel++) waveColors[layer][channel] += (colors[layer][channel] - waveColors[layer][channel]) * .035;
        }
        const sceneActive = preferences.wavesEnabled && preferences.backdropPreset !== "waves";
        sceneCanvas.style.opacity = sceneActive ? "1" : "0";
        canvas.style.opacity = sceneActive || (preferences.backdropPreset === "waves" && !preferences.wavesEnabled) ? "0" : "1";
        if (sceneActive && scene) {
          const sceneReactive: Reactivity = { ...reactive, bass: reactive.bass * preferences.bassReactivity, mid: reactive.mid * preferences.vocalReactivity, treble: reactive.treble * preferences.trebleReactivity };
          presetScene(scene, preferences.backdropPreset, sceneCanvas.width, sceneCanvas.height, elapsed, now / 1000, frameDelta, sceneReactive, [...baseColor] as Color, [[...waveColors[0]], [...waveColors[1]], [...waveColors[2]]], envelope, waveHistory, tunnelState, curtainState);
        } else if (baseline && splineSettings && particleSettings) {
          splineSettings.opacity = baseline.spline.opacity * opacityScale;
          splineSettings.layerAmplitudes[0] = preferences.wavesEnabled && preferences.backdropPreset === "waves" ? baseline.spline.layerAmplitudes[0] + reactive.bass * 1.65 * preferences.bassReactivity : 0;
          splineSettings.layerAmplitudes[1] = preferences.wavesEnabled && preferences.backdropPreset === "waves" ? baseline.spline.layerAmplitudes[1] + reactive.mid * 1.3 * preferences.vocalReactivity : 0;
          splineSettings.layerAmplitudes[2] = preferences.wavesEnabled && preferences.backdropPreset === "waves" ? baseline.spline.layerAmplitudes[2] + reactive.treble * 1.05 * preferences.trebleReactivity : 0;
          particleSettings.count = preferences.wavesEnabled && preferences.backdropPreset === "waves" ? Math.round((baseline.particles.count + reactive.treble * 2600) / 100) * 100 : 0;
          splineSettings.colorR += (baseColor[0] - splineSettings.colorR) * .025;
          splineSettings.colorG += (baseColor[1] - splineSettings.colorG) * .025;
          splineSettings.colorB += (baseColor[2] - splineSettings.colorB) * .025;
          for (let layer = 0; layer < splineSettings.layerColors.length; layer++) {
            for (let channel = 0; channel < 3; channel++) splineSettings.layerColors[layer][channel] += (waveColors[layer][channel] - splineSettings.layerColors[layer][channel]) * .035;
          }
          spline.render(elapsed);
          particles.render(elapsed + 417);
        }
        if (!reduced && !cancelled) animation = requestAnimationFrame(frame);
      };
      animation = requestAnimationFrame(frame);
    }

    start().catch(() => {});
    return () => { cancelled = true; cancelAnimationFrame(animation); removeResize(); window.removeEventListener("echora:audio-reactivity", receiveAudio); window.removeEventListener("echora:backdrop-mode", receiveMode); window.removeEventListener("echora:track-palette", receivePalette); window.removeEventListener("echora:audio-waveform", receiveWaveform); window.removeEventListener("echora:track-change", resetTunnel); window.removeEventListener("echora:playback-preferences", receivePreferences); };
  }, []);

  return <div className={styles.backdrop} aria-hidden="true"><canvas ref={glRef} /><canvas ref={sceneRef} className={styles.scene} /></div>;
}
