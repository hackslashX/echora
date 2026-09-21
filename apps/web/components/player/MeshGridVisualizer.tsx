"use client";

import type { TrackPalette } from "./artworkPalette";
import type { VisualFrame } from "./visualFeatures";
import * as THREE from "three";
import { useEffect, useRef } from "react";
import { readPlaybackPreferences, type PlaybackPreferences } from "./playbackPreferences";
import { compactLayoutEvent, readCompactLayoutPreference } from "../shell/layoutPreference";
import styles from "./MeshGridVisualizer.module.css";

const vertexShader = `
  attribute vec3 barycentric;
  uniform float travel, bass, mid, treble, pulse;
  varying vec3 vBarycentric;
  varying float vRadius, vCrest, vDistance;
  void main() {
    vec2 ground = position.xy;
    float radius = length(ground);
    float ring = sin(radius * 1.35 - travel * 7.0);
    float crest = pow(.5 + .5 * ring, 5.0);
    float rough = sin(ground.x * 3.7 + ground.y * 2.1 + travel) *
      cos(ground.y * 4.3 - ground.x * 1.4 - travel * .7);
    float height = -radius * radius * .009;
    // Amplify audio displacement, leaving the idle shape and lighting unchanged.
    height += ring * (.08 + bass * .975 + pulse * .45);
    height += rough * (.025 + mid * .42 + treble * .18);
    vec4 view = modelViewMatrix * vec4(ground.x, height, ground.y, 1.0);
    vBarycentric = barycentric;
    vRadius = radius;
    vCrest = crest;
    vDistance = -view.z;
    gl_Position = projectionMatrix * view;
  }
`;

const fragmentShader = `
  uniform vec3 colorA, colorB, colorC, colorD, colorE;
  uniform float colorCount, travel, energy, treble, visibility;
  varying vec3 vBarycentric;
  varying float vRadius, vCrest, vDistance;
  vec3 palette(float index) {
    return index < 1.0 ? colorA : index < 2.0 ? colorB : index < 3.0 ? colorC : index < 4.0 ? colorD : colorE;
  }
  void main() {
    vec3 pixelDistance = vBarycentric / max(fwidth(vBarycentric), vec3(.00001));
    float edge = min(pixelDistance.x, min(pixelDistance.y, pixelDistance.z));
    float core = 1.0 - smoothstep(.25, 1.0, edge);
    float halo = exp(-edge * .85) * .22;
    float band = mod(vRadius * .22, colorCount);
    vec3 color = mix(palette(floor(band)), palette(mod(floor(band) + 1.0, colorCount)), smoothstep(.15, .85, fract(band)));
    float light = .2 + vCrest * (.35 + energy * .55) + treble * .16;
    float fog = 1.0 - smoothstep(24.0, 64.0, vDistance);
    vec3 rgb = color * (core + halo) * light * fog * visibility;
    gl_FragColor = vec4(rgb, 1.0);
  }
`;

/** Triangulated terrain with radial audio-driven waves and per-edge glow. */
export default function MeshGridVisualizer() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    const compact = window.matchMedia("(max-width:1199px), (max-height:719px)");
    let preferences = readPlaybackPreferences();
    let renderer: THREE.WebGLRenderer | null = null;
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(58, 1, .1, 100);
    camera.position.set(0, 5.2, 18);
    camera.lookAt(0, -2, -7);
    const base = new THREE.PlaneGeometry(80, 80, 180, 180);
    // Seeded vertex offsets break the rectangular lattice without cracks.
    const positions = base.getAttribute("position");
    const random = (n: number) => { const value = Math.sin(n * 127.1) * 43758.5453; return value - Math.floor(value); };
    for (let i = 0; i < positions.count; i++) {
      positions.setXY(i, positions.getX(i) + (random(i + 1) - .5) * .23, positions.getY(i) + (random(i + 907) - .5) * .23);
    }
    const geometry = base.toNonIndexed();
    base.dispose();
    const barycentric = new Float32Array(geometry.getAttribute("position").count * 3);
    for (let i = 0; i < barycentric.length / 3; i++) barycentric[i * 3 + i % 3] = 1;
    geometry.setAttribute("barycentric", new THREE.BufferAttribute(barycentric, 3));
    const targetColors = [new THREE.Vector3(.48, .98, .92), new THREE.Vector3(.76, .66, 1), new THREE.Vector3(.55, .8, 1), new THREE.Vector3(.48, .98, .92), new THREE.Vector3(.76, .66, 1)];
    const colorNames = ["colorA", "colorB", "colorC", "colorD", "colorE"] as const;
    const material = new THREE.ShaderMaterial({
      depthTest: true, depthWrite: true, side: THREE.DoubleSide,
      uniforms: {
        colorA: { value: targetColors[0].clone() },
        colorB: { value: targetColors[1].clone() },
        colorC: { value: targetColors[2].clone() },
        colorD: { value: targetColors[3].clone() },
        colorE: { value: targetColors[4].clone() },
        colorCount: { value: 3 },
        resolution: { value: new THREE.Vector2(1, 1) },
        travel: { value: 0 }, energy: { value: 0 }, visibility: { value: .38 },
        bass: { value: 0 }, mid: { value: 0 }, treble: { value: 0 }, pulse: { value: 0 },
      },
      vertexShader,
      fragmentShader,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.frustumCulled = false;
    scene.add(mesh);
    let frame = 0, lastFrame = 0, lastAudio = -Infinity, targetEnergy = 0, playing = true;
    let active = false, failed = false, fade = 0;
    let targetBass = 0, targetMid = 0, targetTreble = 0, pendingPulse = 0;
    let bpm = 0, travelSpeed = 0;
    const resize = () => {
      if (!renderer) return;
      const bounds = canvas.getBoundingClientRect();
      renderer.setPixelRatio(Math.min(1.5, window.devicePixelRatio || 1));
      renderer.setSize(Math.max(1, bounds.width), Math.max(1, bounds.height), false);
      renderer.getDrawingBufferSize(material.uniforms.resolution.value);
      camera.aspect = Math.max(1, bounds.width) / Math.max(1, bounds.height);
      camera.updateProjectionMatrix();
    };
    const draw = (now: number) => {
      if (!active || !renderer) return;
      frame = requestAnimationFrame(draw);
      const interval = preferences.waveFrameRate === "uncapped" ? 0 : 1000 / Number(preferences.waveFrameRate);
      if (now - lastFrame < interval) return;
      const dt = Math.min(.05, (now - lastFrame) / 1000 || .016);
      lastFrame = now;
      const audible = playing && now - lastAudio < 700;
      // A reversible 800ms fade. Smoothstep softens both ends without a jump
      // when playback toggles again halfway through a transition.
      fade = THREE.MathUtils.clamp(fade + (audible ? 1 : -1) * dt / .8, 0, 1);
      material.uniforms.visibility.value = .38 + .62 * fade * fade * (3 - 2 * fade);
      const energy = material.uniforms.energy.value;
      material.uniforms.energy.value += ((audible ? targetEnergy : 0) - energy) * (1 - Math.exp(-dt * 3));
      for (const [name, target] of [["bass", targetBass], ["mid", targetMid], ["treble", targetTreble]] as const) {
        const current = material.uniforms[name].value;
        const next = audible ? target : 0;
        // Fast attack preserves beats; slower release avoids strobing.
        const response = next > current ? 18 : 5;
        material.uniforms[name].value += (next - current) * (1 - Math.exp(-dt * response));
      }
      material.uniforms.pulse.value = Math.max(
        material.uniforms.pulse.value * Math.exp(-dt * 5), audible ? pendingPulse : 0,
      );
      pendingPulse = 0;
      const rate = preferences.animationSpeed === "slow" ? .65 : preferences.animationSpeed === "fast" ? 1.45 : 1;
      // Volume controls the push; detected tempo controls the pace. Smooth
      // speed changes rather than jumping the ripples' position on each beat.
      const tempoScale = THREE.MathUtils.clamp(Math.pow((bpm || 100) / 100, 1.3), .5, 2.2);
      const targetSpeed = audible
        ? (.08 + energy * .32 + material.uniforms.bass.value * .32 + material.uniforms.pulse.value * .16) * tempoScale : 0;
      travelSpeed += (targetSpeed - travelSpeed) * (1 - Math.exp(-dt * 3));
      material.uniforms.travel.value += dt * rate * travelSpeed;
      colorNames.forEach((name, index) => material.uniforms[name].value.lerp(targetColors[index], 1 - Math.exp(-dt * 2)));
      renderer.render(scene, camera);
    };
    const sync = () => {
      const next = !failed && preferences.wavesEnabled && preferences.backdropPreset === "meshgrid"
        && !compact.matches && !readCompactLayoutPreference() && !reduced.matches && !document.hidden;
      canvas.style.display = next ? "block" : "none";
      if (next && !renderer) {
        try { renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: false }); resize(); }
        catch { failed = true; canvas.style.display = "none"; return; }
      }
      if (next === active) return;
      active = next;
      cancelAnimationFrame(frame);
      if (active) { lastFrame = performance.now(); frame = requestAnimationFrame(draw); }
    };
    const receivePreferences = (event: Event) => { preferences = (event as CustomEvent<PlaybackPreferences>).detail; sync(); };
    const receiveAudio = (event: Event) => {
      const detail = (event as CustomEvent<VisualFrame>).detail;
      if (!detail.active) { reset(); return; }
      playing = true; bpm = detail.bpm ?? 0;
      targetEnergy = Math.min(1, detail.bass * preferences.bassReactivity * .5 + detail.mid * preferences.vocalReactivity * .35 + detail.treble * preferences.trebleReactivity * .15);
      targetBass = Math.min(1, detail.bass * preferences.bassReactivity * 1.4);
      targetMid = Math.min(1, detail.mid * preferences.vocalReactivity * 1.5);
      targetTreble = Math.min(1, detail.treble * preferences.trebleReactivity * 1.8);
      pendingPulse = Math.max(pendingPulse, Math.min(1,
        ((detail.bassAttack ?? 0) * 5 + (detail.beat ? .55 : 0)) * preferences.bassReactivity,
      ));
      const now = performance.now();
      lastAudio = now;
    };
    const receivePalette = (event: Event) => {
      const { palette } = (event as CustomEvent<{ palette: TrackPalette | null }>).detail;
      // Pause publishes null. Keep the current artwork colors until a new palette arrives.
      if (palette) {
        const colors = palette.trails?.length ? palette.trails : palette.waves;
        material.uniforms.colorCount.value = Math.min(5, colors.length);
        targetColors.forEach((color, index) => color.fromArray(colors[index % colors.length]));
      }
    };
    const receiveState = (event: Event) => { playing = Boolean((event as CustomEvent<boolean>).detail); };
    const reset = () => {
      targetEnergy = 0; targetBass = 0; targetMid = 0; targetTreble = 0; pendingPulse = 0; lastAudio = -Infinity;
      // Neutral frames arrive repeatedly while paused. Let the render loop
      // release the bands, pulse, and speed instead of cutting them to zero.
    };
    const events: [string, EventListener][] = [
      ["echora:playback-preferences", receivePreferences], ["echora:visual-frame", receiveAudio],
      ["echora:track-palette", receivePalette], ["echora:playback-state", receiveState], ["echora:track-change", reset],
      [compactLayoutEvent, sync], ["resize", resize],
    ];
    events.forEach(([name, handler]) => window.addEventListener(name, handler));
    compact.addEventListener("change", sync); reduced.addEventListener("change", sync);
    document.addEventListener("visibilitychange", sync);
    sync();
    window.dispatchEvent(new Event("echora:playback-state-request"));
    return () => {
      cancelAnimationFrame(frame);
      events.forEach(([name, handler]) => window.removeEventListener(name, handler));
      compact.removeEventListener("change", sync); reduced.removeEventListener("change", sync);
      document.removeEventListener("visibilitychange", sync);
      geometry.dispose(); material.dispose(); renderer?.dispose();
    };
  }, []);
  return <canvas ref={ref} className={styles.signal} aria-hidden="true" />;
}
