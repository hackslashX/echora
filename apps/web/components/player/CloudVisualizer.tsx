"use client";

import type { VisualFrame } from "./visualFeatures";
import * as THREE from "three";
import { useEffect, useRef } from "react";
import { readPlaybackPreferences, type PlaybackPreferences } from "./playbackPreferences";
import { compactLayoutEvent, readCompactLayoutPreference } from "../shell/layoutPreference";
import { CloudResponse } from "./cloudResponse";
import { cloudFragmentShader } from "./cloudShader";
import styles from "./CloudVisualizer.module.css";

export default function CloudVisualizer() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const compact = window.matchMedia("(max-width:1199px), (max-height:719px)");
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    let preferences = readPlaybackPreferences();
    let renderer: THREE.WebGLRenderer | null = null;
    let active = false, failed = false, playing = false, frame = 0, lastFrame = 0;
    const response = new CloudResponse();
    const targetTint = new THREE.Vector3(.38, .48, .63);
    const scene = new THREE.Scene();
    const camera = new THREE.Camera();
    const geometry = new THREE.PlaneGeometry(2, 2);
    const material = new THREE.ShaderMaterial({
      depthTest: false, depthWrite: false,
      uniforms: {
        resolution: { value: new THREE.Vector2(1, 1) },
        tint: { value: targetTint.clone() },
        travel: { value: 0 }, bass: { value: 0 }, mid: { value: 0 }, treble: { value: 0 },
        glow: { value: 0 }, strike: { value: 0 }, seed: { value: 1 },
      },
      vertexShader: "varying vec2 vUv; void main(){vUv=uv;gl_Position=vec4(position.xy,0.0,1.0);}",
      fragmentShader: cloudFragmentShader,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.frustumCulled = false;
    scene.add(mesh);
    const resize = () => {
      if (!renderer) return;
      const bounds = canvas.getBoundingClientRect();
      // The shader stays below native retina resolution, but 1,200 pixels
      // across retains the smaller cloud folds and lightning branches.
      const scale = Math.min(.78, 1200 / Math.max(1, bounds.width));
      renderer.setPixelRatio(1);
      renderer.setSize(Math.max(1, Math.round(bounds.width * scale)), Math.max(1, Math.round(bounds.height * scale)), false);
      renderer.getDrawingBufferSize(material.uniforms.resolution.value);
    };
    const draw = (now: number) => {
      if (!active || !renderer) return;
      frame = requestAnimationFrame(draw);
      const interval = preferences.waveFrameRate === "uncapped" ? 0 : 1000 / Number(preferences.waveFrameRate);
      if (now - lastFrame < interval) return;
      const dt = Math.min(.1, (now - lastFrame) / 1000);
      lastFrame = now;
      const rate = preferences.animationSpeed === "slow" ? .65 : preferences.animationSpeed === "fast" ? 1.45 : 1;
      response.step(dt, now / 1000, playing, rate);
      for (const key of ["travel", "bass", "mid", "treble", "glow", "strike", "seed"] as const) material.uniforms[key].value = response[key];
      material.uniforms.tint.value.lerp(targetTint, 1 - Math.exp(-dt * .6));
      renderer.render(scene, camera);
    };
    const sync = () => {
      const next = !failed && preferences.wavesEnabled && preferences.backdropPreset === "clouds"
        && !compact.matches && !readCompactLayoutPreference() && !reduced.matches && !document.hidden;
      canvas.style.display = next ? "block" : "none";
      if (next && !renderer) {
        try {
          renderer = new THREE.WebGLRenderer({ canvas, alpha: false, antialias: false, powerPreference: "low-power" });
          resize();
        } catch { failed = true; canvas.style.display = "none"; return; }
      }
      if (next === active) return;
      active = next;
      cancelAnimationFrame(frame);
      response.reset();
      if (active) { resize(); lastFrame = performance.now(); frame = requestAnimationFrame(draw); }
    };
    const receivePreferences = (event: Event) => { preferences = (event as CustomEvent<PlaybackPreferences>).detail; sync(); };
    const receiveAudio = (event: Event) => {
      const detail = (event as CustomEvent<VisualFrame>).detail;
      if (!detail.active) { response.reset(); return; }
      playing = true;
      if (active) response.receive(detail, preferences, performance.now() / 1000);
    };
    const receivePalette = (event: Event) => {
      const detail = (event as CustomEvent<{ active: boolean; palette: { waves: number[][] } | null }>).detail;
      const palette = detail.active ? detail.palette : null;
      if (palette?.waves[0]) targetTint.fromArray(palette.waves[0]);
      else targetTint.set(.38, .48, .63);
    };
    const receiveState = (event: Event) => {
      playing = Boolean((event as CustomEvent<boolean>).detail);
      if (!playing) response.reset();
    };
    const reset = () => response.reset();
    const lost = (event: Event) => { event.preventDefault(); failed = true; sync(); };
    const restored = () => { failed = false; sync(); };
    const events: [string, EventListener][] = [
      ["echora:playback-preferences", receivePreferences], ["echora:visual-frame", receiveAudio],
      ["echora:track-palette", receivePalette], ["echora:playback-state", receiveState],
      ["echora:track-change", reset], [compactLayoutEvent, sync], ["resize", resize],
    ];
    events.forEach(([name, handler]) => window.addEventListener(name, handler));
    // Provider effects register after this sibling backdrop. Defer one turn so
    // the request can retrieve the current state even when playback began first.
    const stateRequest = window.setTimeout(() => window.dispatchEvent(new Event("echora:playback-state-request")), 0);
    compact.addEventListener("change", sync); reduced.addEventListener("change", sync);
    document.addEventListener("visibilitychange", sync);
    canvas.addEventListener("webglcontextlost", lost); canvas.addEventListener("webglcontextrestored", restored);
    sync();
    return () => {
      cancelAnimationFrame(frame);
      window.clearTimeout(stateRequest);
      events.forEach(([name, handler]) => window.removeEventListener(name, handler));
      compact.removeEventListener("change", sync); reduced.removeEventListener("change", sync);
      document.removeEventListener("visibilitychange", sync);
      canvas.removeEventListener("webglcontextlost", lost); canvas.removeEventListener("webglcontextrestored", restored);
      geometry.dispose(); material.dispose(); renderer?.dispose();
    };
  }, []);
  // Backdrop's generic canvas rule is deliberately broad. Start hidden so this
  // opaque layer cannot cover the existing visualizers before sync enables it.
  return <canvas ref={ref} className={styles.clouds} style={{ display: "none" }} aria-hidden="true" />;
}
