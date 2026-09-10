"use client";

import * as THREE from "three";
import { useEffect, useRef } from "react";
import { readPlaybackPreferences, type PlaybackPreferences } from "./playbackPreferences";
import { compactLayoutEvent, readCompactLayoutPreference } from "../shell/layoutPreference";
import styles from "./SignalVisualizer.module.css";

const SAMPLES = 256;
const fragmentShader = `
  uniform vec2 resolution;
  uniform sampler2D waveform;
  uniform vec3 tint;
  uniform float travel;
  uniform float energy;
  uniform float bass;
  uniform float mid;
  uniform float treble;
  uniform float pulse;
  uniform float mode;
  uniform float opacity;
  varying vec2 vUv;
  void main() {
    vec2 p = vUv - .5;
    p.x *= resolution.x / resolution.y;
    float light = 0.0;
    if (mode < .5) {
      float sampleValue = texture2D(waveform, vec2(vUv.x, .5)).r * 2.0 - 1.0;
      float y = sampleValue * (.12 + energy * .06);
      float distanceToTrace = abs(vUv.y - .5 - y);
      float aa = max(fwidth(vUv.y - y), 1.0 / resolution.y);
      float core = 1.0 - smoothstep(0.0, aa * 1.4, distanceToTrace);
      float halo = exp(-distanceToTrace * resolution.y * .17);
      float ends = smoothstep(0.0, .1, vUv.x) * smoothstep(0.0, .1, 1.0-vUv.x);
      light = (core * .42 + halo * .12) * ends;
    } else {
      // Fixed vanishing point. Log spacing gives depth without camera movement.
      float radius = length(p * vec2(1.0, 1.12));
      float angle = atan(p.y, p.x);
      // Small organic ripples follow the bands, with no camera shake or rotation.
      float ripple = sin(angle * 3.0 + travel * .7) * mid * .018
        + sin(angle * 7.0 - travel * .4) * treble * .006;
      float swell = 1.0 + bass * .04 + pulse * .025 + ripple;
      float depth = -log(max(radius / swell, .025)) * 3.2 + travel;
      float ringDistance = abs(fract(depth) - .5);
      float aa = max(fwidth(depth), .006);
      float ring = 1.0 - smoothstep(.008, .008 + aa, ringDistance);
      float halo = exp(-ringDistance * 28.0);
      float aperture = smoothstep(.10, .30, radius);
      float outerFade = 1.0 - smoothstep(.55, 1.15, radius);
      float highlights = pow(.5 + .5 * cos(angle * 3.0 + travel * .35), 3.0);
      float depthAccent = .65 + .35 * sin(floor(depth) * 1.7 + travel * .5);
      float ringLight = .16 + bass * .24 + pulse * .32 * depthAccent;
      float haloLight = .055 + mid * .055 + treble * highlights * .14;
      light = (ring * ringLight + halo * haloLight) * aperture * outerFade * .55;
    }
    // A dark centre keeps lyrics and foreground controls readable.
    gl_FragColor = vec4(tint * light * (.65 + energy * .35), opacity);
  }
`;

/** One GPU draw call for the scope or the quiet, fixed-camera tunnel. */
export default function SignalVisualizer() {
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
    const samples = new Uint8Array(SAMPLES).fill(128);
    const texture = new THREE.DataTexture(samples, SAMPLES, 1, THREE.RedFormat);
    texture.minFilter = THREE.LinearFilter;
    texture.magFilter = THREE.LinearFilter;
    texture.needsUpdate = true;
    const geometry = new THREE.PlaneGeometry(2, 2);
    const material = new THREE.ShaderMaterial({
      depthTest: false, depthWrite: false,
      uniforms: {
        waveform: { value: texture }, resolution: { value: new THREE.Vector2(1, 1) },
        tint: { value: new THREE.Vector3(.3, .7, .65) },
        mode: { value: 0 }, travel: { value: 0 }, energy: { value: 0 }, opacity: { value: 1 },
        bass: { value: 0 }, mid: { value: 0 }, treble: { value: 0 }, pulse: { value: 0 },
      },
      vertexShader: "varying vec2 vUv; void main(){vUv=uv;gl_Position=vec4(position.xy,0.0,1.0);}",
      fragmentShader,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.frustumCulled = false;
    scene.add(mesh);
    const targetColor = new THREE.Vector3(.3, .7, .65);
    let frame = 0, lastFrame = 0, lastAudio = -Infinity, targetEnergy = 0, playing = true;
    let active = false, failed = false;
    let targetBass = 0, targetMid = 0, targetTreble = 0, pendingPulse = 0;
    let bpm = 100, lastBeat = -Infinity, travelSpeed = 0;
    const beatIntervals: number[] = [];
    const resize = () => {
      if (!renderer) return;
      const bounds = canvas.getBoundingClientRect();
      renderer.setPixelRatio(Math.min(1.5, window.devicePixelRatio || 1));
      renderer.setSize(Math.max(1, bounds.width), Math.max(1, bounds.height), false);
      renderer.getDrawingBufferSize(material.uniforms.resolution.value);
    };
    const draw = (now: number) => {
      if (!active || !renderer) return;
      frame = requestAnimationFrame(draw);
      const interval = preferences.waveFrameRate === "uncapped" ? 0 : 1000 / Number(preferences.waveFrameRate);
      if (now - lastFrame < interval) return;
      const dt = Math.min(.05, (now - lastFrame) / 1000 || .016);
      lastFrame = now;
      const audible = playing && now - lastAudio < 700;
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
      material.uniforms.tint.value.lerp(targetColor, 1 - Math.exp(-dt * 2));
      const rate = preferences.animationSpeed === "slow" ? .65 : preferences.animationSpeed === "fast" ? 1.45 : 1;
      // Volume controls the push; detected tempo controls the pace. Smooth
      // speed changes rather than jumping the tunnel's position on each beat.
      const tempoScale = THREE.MathUtils.clamp(Math.pow(bpm / 100, 1.3), .5, 2.2);
      const targetSpeed = audible
        ? (.025 + energy * .46 + material.uniforms.pulse.value * .10) * tempoScale : 0;
      travelSpeed += (targetSpeed - travelSpeed) * (1 - Math.exp(-dt * 3));
      material.uniforms.travel.value += dt * rate * travelSpeed;
      if (!audible) {
        for (let i = 0; i < SAMPLES; i++) samples[i] = Math.round(samples[i] + (128 - samples[i]) * Math.min(1, dt * 8));
        texture.needsUpdate = true;
      }
      renderer.render(scene, camera);
    };
    const sync = () => {
      const next = !failed && preferences.wavesEnabled && ["oscilloscope", "void"].includes(preferences.backdropPreset)
        && !compact.matches && !readCompactLayoutPreference() && !reduced.matches && !document.hidden;
      canvas.style.display = next ? "block" : "none";
      if (next && !renderer) {
        try { renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: false }); resize(); }
        catch { failed = true; canvas.style.display = "none"; return; }
      }
      material.uniforms.mode.value = preferences.backdropPreset === "void" ? 1 : 0;
      if (next === active) return;
      active = next;
      cancelAnimationFrame(frame);
      if (active) { lastFrame = performance.now(); frame = requestAnimationFrame(draw); }
    };
    const receivePreferences = (event: Event) => { preferences = (event as CustomEvent<PlaybackPreferences>).detail; sync(); };
    const receiveAudio = (event: Event) => {
      const detail = (event as CustomEvent<{ bass: number; mid: number; treble: number; onset?: boolean; bassAttack?: number }>).detail;
      targetEnergy = Math.min(1, detail.bass * preferences.bassReactivity * .5 + detail.mid * preferences.vocalReactivity * .35 + detail.treble * preferences.trebleReactivity * .15);
      targetBass = Math.min(1, detail.bass * preferences.bassReactivity * 1.4);
      targetMid = Math.min(1, detail.mid * preferences.vocalReactivity * 1.5);
      targetTreble = Math.min(1, detail.treble * preferences.trebleReactivity * 1.8);
      pendingPulse = Math.max(pendingPulse, Math.min(1,
        ((detail.bassAttack ?? 0) * 5 + (detail.onset ? .55 : 0)) * preferences.bassReactivity,
      ));
      const now = performance.now();
      if (detail.onset && playing) {
        const interval = (now - lastBeat) / 1000;
        if (interval >= .30 && interval <= 1.2) {
          beatIntervals.push(interval);
          if (beatIntervals.length > 7) beatIntervals.shift();
          const sorted = [...beatIntervals].sort((a, b) => a - b);
          const median = sorted[Math.floor(sorted.length / 2)];
          bpm += (60 / median - bpm) * .3;
        } else if (interval > 1.2) beatIntervals.length = 0;
        lastBeat = now;
      }
      lastAudio = now;
    };
    const receiveWaveform = (event: Event) => {
      if (!active || preferences.backdropPreset !== "oscilloscope") return;
      const bins = (event as CustomEvent<Uint8Array>).detail;
      for (let i = 0; i < SAMPLES; i++) {
        const start = Math.floor(i * bins.length / SAMPLES);
        const end = Math.min(bins.length, Math.max(start + 1, Math.floor((i + 1) * bins.length / SAMPLES)));
        let sum = 0;
        for (let j = start; j < end; j++) sum += bins[j];
        samples[i] = end > start ? Math.round(sum / (end - start)) : 128;
      }
      texture.needsUpdate = true;
    };
    const receivePalette = (event: Event) => {
      const detail = (event as CustomEvent<{ palette: { waves: [number[], number[], number[]] } | null }>).detail;
      if (detail.palette) targetColor.fromArray(detail.palette.waves[0]);
    };
    const receiveState = (event: Event) => { playing = Boolean((event as CustomEvent<boolean>).detail); };
    const reset = () => {
      samples.fill(128); texture.needsUpdate = true;
      targetEnergy = 0; targetBass = 0; targetMid = 0; targetTreble = 0; pendingPulse = 0; lastAudio = -Infinity;
      material.uniforms.pulse.value = 0;
      bpm = 100; lastBeat = -Infinity; travelSpeed = 0; beatIntervals.length = 0;
    };
    const events: [string, EventListener][] = [
      ["echora:playback-preferences", receivePreferences], ["echora:audio-reactivity", receiveAudio],
      ["echora:audio-waveform", receiveWaveform], ["echora:track-palette", receivePalette],
      ["echora:playback-state", receiveState], ["echora:track-change", reset],
      [compactLayoutEvent, sync], ["resize", resize],
    ];
    events.forEach(([name, handler]) => window.addEventListener(name, handler));
    compact.addEventListener("change", sync); reduced.addEventListener("change", sync);
    document.addEventListener("visibilitychange", sync);
    sync();
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
