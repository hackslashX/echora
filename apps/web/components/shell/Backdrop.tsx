"use client";

import { useEffect, useRef } from "react";
import { PlaybackPreferences, readPlaybackPreferences } from "../player/playbackPreferences";
import styles from "./Backdrop.module.css";

type RenderLayer = { render: (time: number) => void };
type Color = [number, number, number];
type SplineSettings = { flowSpeed: number; bandAmplitude: number; waveHeightScale: number; brightness: number; opacity: number; layerAmplitudes: number[]; layerColors: Color[]; colorR: number; colorG: number; colorB: number };
type ParticleSettings = { count: number; flowSpeed: number; opacity: number; sizeBase: number; sizeVar: number };
type Reactivity = { bass: number; mid: number; treble: number; level: number };
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

export default function Backdrop() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const element = canvasRef.current;
    if (!element) return;
    const canvas: HTMLCanvasElement = element;
    let cancelled = false;
    let animation = 0;
    let removeResize = () => {};
    const target: Reactivity = { bass: 0, mid: 0, treble: 0, level: 0 };
    let preferences = readPlaybackPreferences();
    let paletteTarget: { background: Color; waves: Color[] } | null = null;
    let opacityScale = 1;
    let targetOpacityScale = 1;
    const reactive: Reactivity = { ...target };
    const receiveAudio = (event: Event) => Object.assign(target, (event as CustomEvent<Reactivity>).detail);
    const receiveMode = (event: Event) => { targetOpacityScale = (event as CustomEvent<{ waveOpacity: number }>).detail.waveOpacity; };
    const receivePreferences = (event: Event) => { preferences = (event as CustomEvent<PlaybackPreferences>).detail; };
    const receivePalette = (event: Event) => {
      const detail = (event as CustomEvent<{ active: boolean; palette: { background: Color; waves: Color[] } | null }>).detail;
      paletteTarget = detail.active ? detail.palette : null;
    };
    window.addEventListener("echora:audio-reactivity", receiveAudio);
    window.addEventListener("echora:backdrop-mode", receiveMode);
    window.addEventListener("echora:track-palette", receivePalette);
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
        const width = Math.max(1, Math.floor(canvas.clientWidth * ratio));
        const height = Math.max(1, Math.floor(canvas.clientHeight * ratio));
        if (canvas.width !== width || canvas.height !== height) {
          canvas.width = width; canvas.height = height; gl.viewport(0, 0, width, height);
        }
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
      let elapsed = 0;
      const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      const frame = (now: number) => {
        elapsed += Math.max(0, now - previous) / 1000;
        previous = now;
        for (const key of Object.keys(reactive) as (keyof Reactivity)[]) reactive[key] += (target[key] - reactive[key]) * .11;
        opacityScale += (targetOpacityScale - opacityScale) * .035;
        if (baseline && splineSettings && particleSettings) {
          splineSettings.opacity = baseline.spline.opacity * opacityScale;
          splineSettings.layerAmplitudes[0] = preferences.wavesEnabled ? baseline.spline.layerAmplitudes[0] + reactive.bass * 1.65 * preferences.bassReactivity : 0;
          splineSettings.layerAmplitudes[1] = preferences.wavesEnabled ? baseline.spline.layerAmplitudes[1] + reactive.mid * 1.3 * preferences.vocalReactivity : 0;
          splineSettings.layerAmplitudes[2] = preferences.wavesEnabled ? baseline.spline.layerAmplitudes[2] + reactive.treble * 1.05 * preferences.trebleReactivity : 0;
          particleSettings.count = preferences.wavesEnabled ? Math.round((baseline.particles.count + reactive.treble * 2600) / 100) * 100 : 0;
          const background = paletteTarget?.background || baseline.spline.background;
          splineSettings.colorR += (background[0] - splineSettings.colorR) * .025;
          splineSettings.colorG += (background[1] - splineSettings.colorG) * .025;
          splineSettings.colorB += (background[2] - splineSettings.colorB) * .025;
          const colors = paletteTarget?.waves || baseline.spline.layerColors;
          for (let layer = 0; layer < splineSettings.layerColors.length; layer++) {
            for (let channel = 0; channel < 3; channel++) splineSettings.layerColors[layer][channel] += (colors[layer][channel] - splineSettings.layerColors[layer][channel]) * .035;
          }
        }
        spline.render(elapsed);
        particles.render(elapsed + 417);
        if (!reduced && !cancelled) animation = requestAnimationFrame(frame);
      };
      animation = requestAnimationFrame(frame);
    }

    start().catch(() => {});
    return () => { cancelled = true; cancelAnimationFrame(animation); removeResize(); window.removeEventListener("echora:audio-reactivity", receiveAudio); window.removeEventListener("echora:backdrop-mode", receiveMode); window.removeEventListener("echora:track-palette", receivePalette); window.removeEventListener("echora:playback-preferences", receivePreferences); };
  }, []);

  return <div className={styles.backdrop} aria-hidden="true"><canvas ref={canvasRef} /></div>;
}
