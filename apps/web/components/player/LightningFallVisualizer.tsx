"use client";

import type { TrackPalette } from "./artworkPalette";
import type { VisualFrame } from "./visualFeatures";
import * as THREE from "three";
import { useEffect, useRef } from "react";
import { readPlaybackPreferences, type PlaybackPreferences } from "./playbackPreferences";
import { compactLayoutEvent, readCompactLayoutPreference } from "../shell/layoutPreference";
import styles from "./LightningFallVisualizer.module.css";

const fragmentShader = `
  uniform sampler2D spectrum;
  uniform float travel, energy, bass, mid, treble, pulse, visibility, colorCount;
  uniform vec3 colorA, colorB, colorC, colorD, colorE;
  varying vec2 vUv;
  float hash(float n) { return fract(sin(n * 127.1) * 43758.5453); }
  void main() {
    float y = 1.0 - vUv.y;
    float spread = .16 + 1.65 * pow(y, 3.3);
    float bend = sin(y * 4.0 + travel * .3) * mid * .006 * y;
    float lane = ((vUv.x - .5 - bend) / spread + .5) * 150.0;
    float id = floor(lane);
    float seed = hash(id);
    // Nearby threads share neighboring frequency bands, low to high.
    float frequency = texture2D(spectrum, vec2(clamp((id + .5) / 150.0, 0.0, 1.0), .5)).r;
    float offset = .18 + hash(id + 41.0) * .64;
    float distanceToLine = abs(fract(lane) - offset);
    float aa = max(fwidth(lane), .015);
    float thickness = 1.0 + frequency * .25;
    float core = 1.0 - smoothstep(aa * .12, aa * .8 * thickness, distanceToLine);
    float halo = exp(-distanceToLine / (aa * 2.5 * thickness));
    float bloom = exp(-distanceToLine / (aa * 7.0));
    float phase = fract(y * (1.4 + seed * 1.8) - travel * (.7 + seed * .6) + seed * 13.0);
    float streak = smoothstep(.56 - frequency * .12, .96, phase) * (1.0 - smoothstep(.96, 1.0, phase));
    float head = exp(-pow((phase - .96) * 65.0, 2.0));
    float band = mod(id, 3.0);
    float response = band < 1.0 ? bass : band < 2.0 ? mid : treble;
    float colorIndex = floor(seed * colorCount);
    vec3 color = colorIndex < 1.0 ? colorA : colorIndex < 2.0 ? colorB : colorIndex < 3.0 ? colorC : colorIndex < 4.0 ? colorD : colorE;
    float light = .06 + streak * (.4 + response * .85 + energy * .3);
    light += head * treble * .5 + streak * pulse * .25;
    light *= .9 + frequency * .25;
    float edge = step(0.0, id) * step(id, 149.0);
    float depth = .26 + .74 * smoothstep(0.0, .85, y);
    float glowStrength = .75 + treble * .35;
    vec3 rgb = color * (halo * .48 + bloom * .16) * glowStrength * light;
    rgb += mix(color, vec3(1.0), .22) * core * light * 1.25;
    rgb *= depth * edge;
    rgb += mix(color, vec3(1.0), .5) * head * core * treble * .3 * depth * edge;
    gl_FragColor = vec4(rgb * visibility, 1.0);
  }
`;

/** Dense falling trails with restrained per-frequency modulation. */
export default function LightningFallVisualizer() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    const compact = window.matchMedia("(max-width:1199px), (max-height:719px)");
    let preferences = readPlaybackPreferences();
    let renderer: THREE.WebGLRenderer | null = null;
    const scene = new THREE.Scene();
    const camera = new THREE.Camera();
    const geometry = new THREE.PlaneGeometry(2, 2);
    const bins = new Uint8Array(24);
    const targetBins = new Float32Array(24);
    const smoothBins = new Float32Array(24);
    const texture = new THREE.DataTexture(bins, 24, 1, THREE.RedFormat);
    texture.minFilter = texture.magFilter = THREE.LinearFilter;
    texture.needsUpdate = true;
    const targetColors = [new THREE.Vector3(.48, .98, .92), new THREE.Vector3(.76, .66, 1), new THREE.Vector3(.55, .8, 1), new THREE.Vector3(.48, .98, .92), new THREE.Vector3(.76, .66, 1)];
    const colorNames = ["colorA", "colorB", "colorC", "colorD", "colorE"] as const;
    const material = new THREE.ShaderMaterial({
      depthTest: false, depthWrite: false,
      uniforms: {
        spectrum: { value: texture }, travel: { value: 0 }, energy: { value: 0 },
        bass: { value: 0 }, mid: { value: 0 }, treble: { value: 0 }, pulse: { value: 0 },
        colorA: { value: targetColors[0].clone() }, colorB: { value: targetColors[1].clone() },
        colorC: { value: targetColors[2].clone() }, colorD: { value: targetColors[3].clone() },
        colorE: { value: targetColors[4].clone() }, colorCount: { value: 3 }, visibility: { value: .38 },
      },
      vertexShader: "varying vec2 vUv; void main(){vUv=uv;gl_Position=vec4(position.xy,0.0,1.0);}",
      fragmentShader,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.frustumCulled = false;
    scene.add(mesh);
    let frame = 0, lastFrame = 0, lastAudio = -Infinity, playing = false, fade = 0;
    let active = false, failed = false;
    let trackId: string | null = null;
    let bpm = 100, travelSpeed = 0, pendingPulse = 0;
    const targets = { bass: 0, mid: 0, treble: 0, energy: 0 };
    const resize = () => {
      if (!renderer) return;
      const bounds = canvas.getBoundingClientRect();
      renderer.setPixelRatio(Math.min(1.5, window.devicePixelRatio || 1));
      renderer.setSize(Math.max(1, bounds.width), Math.max(1, bounds.height), false);
    };
    const draw = (now: number) => {
      if (!active || !renderer) return;
      frame = requestAnimationFrame(draw);
      const interval = preferences.waveFrameRate === "uncapped" ? 0 : 1000 / Number(preferences.waveFrameRate);
      if (now - lastFrame < interval) return;
      const dt = Math.min(.05, (now - lastFrame) / 1000 || .016);
      lastFrame = now;
      const audible = playing && now - lastAudio < 700;
      const rate = preferences.animationSpeed === "slow" ? .65 : preferences.animationSpeed === "fast" ? 1.45 : 1;
      fade = THREE.MathUtils.clamp(fade + (audible ? 1 : -1) * dt * rate / .8, 0, 1);
      material.uniforms.visibility.value = .38 + .62 * fade * fade * (3 - 2 * fade);
      for (const name of ["bass", "mid", "treble", "energy"] as const) {
        const value = material.uniforms[name].value;
        const target = audible ? targets[name] : 0;
        material.uniforms[name].value += (target - value) * (1 - Math.exp(-dt * (target > value ? 18 : 5)));
      }
      for (let i = 0; i < 24; i++) {
        const target = audible ? targetBins[i] : 0;
        smoothBins[i] += (target - smoothBins[i]) * (1 - Math.exp(-dt * (target > smoothBins[i] ? 12 : 4)));
        bins[i] = Math.round(smoothBins[i] * 255);
      }
      texture.needsUpdate = true;
      material.uniforms.pulse.value = Math.max(material.uniforms.pulse.value * Math.exp(-dt * 5), audible ? pendingPulse : 0);
      pendingPulse = 0;
      const tempoScale = THREE.MathUtils.clamp(Math.pow(bpm / 100, 1.3), .5, 2.2);
      const speed = audible ? (.08 + material.uniforms.energy.value * .32 + material.uniforms.bass.value * .32 + material.uniforms.pulse.value * .16) * tempoScale : 0;
      travelSpeed += (speed - travelSpeed) * (1 - Math.exp(-dt * 3));
      material.uniforms.travel.value += dt * rate * travelSpeed;
      colorNames.forEach((name, index) => material.uniforms[name].value.lerp(targetColors[index], 1 - Math.exp(-dt * 2)));
      renderer.render(scene, camera);
    };
    const sync = () => {
      const next = !failed && preferences.wavesEnabled && preferences.backdropPreset === "lightningfall"
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
    const clear = () => {
      targetBins.fill(0);
      targets.bass = targets.mid = targets.treble = targets.energy = pendingPulse = 0;
      lastAudio = -Infinity;
    };
    const receivePreferences = (event: Event) => { preferences = (event as CustomEvent<PlaybackPreferences>).detail; sync(); };
    const receiveAudio = (event: Event) => {
      const detail = (event as CustomEvent<VisualFrame>).detail;
      // Pause eases motion and light down without clearing the trails.
      if (!detail.active || !detail.source) { lastAudio = -Infinity; return; }
      if (detail.trackId !== trackId) { clear(); trackId = detail.trackId; }
      playing = true;
      lastAudio = performance.now();
      bpm = detail.bpm || 100;
      targets.bass = Math.min(1, detail.bass * preferences.bassReactivity * 1.4);
      targets.mid = Math.min(1, detail.mid * preferences.vocalReactivity * 1.5);
      targets.treble = Math.min(1, detail.treble * preferences.trebleReactivity * 1.8);
      targets.energy = Math.min(1, detail.bass * preferences.bassReactivity * .5 + detail.mid * preferences.vocalReactivity * .35 + detail.treble * preferences.trebleReactivity * .15);
      pendingPulse = Math.max(pendingPulse, Math.min(1, (detail.bassAttack * 5 + (detail.beat ? .55 : 0)) * preferences.bassReactivity));
      for (let i = 0; i < 24; i++) {
        const hz = detail.source.bandCentersHz[i];
        const gain = hz < 250 ? preferences.bassReactivity : hz < 2000 ? preferences.vocalReactivity : preferences.trebleReactivity;
        targetBins[i] = Math.min(1, Math.max(0, (detail.bands[i] || 0) * gain));
      }
    };
    const receivePalette = (event: Event) => {
      const { palette } = (event as CustomEvent<{ palette: TrackPalette | null }>).detail;
      if (palette) {
        const colors = palette.trails?.length ? palette.trails : palette.waves;
        material.uniforms.colorCount.value = Math.min(5, colors.length);
        targetColors.forEach((color, index) => color.fromArray(colors[index % colors.length]));
      }
    };
    const receiveState = (event: Event) => { playing = Boolean((event as CustomEvent<boolean>).detail); };
    const events: [string, EventListener][] = [
      ["echora:playback-preferences", receivePreferences], ["echora:visual-frame", receiveAudio],
      ["echora:track-palette", receivePalette], ["echora:playback-state", receiveState], ["echora:track-change", clear],
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
      geometry.dispose(); material.dispose(); texture.dispose(); renderer?.dispose();
    };
  }, []);
  return <canvas ref={ref} className={styles.signal} aria-hidden="true" />;
}
