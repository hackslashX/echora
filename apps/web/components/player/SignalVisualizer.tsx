"use client";

import type { VisualFrame } from "./visualFeatures";
import type { TrackPalette } from "./artworkPalette";
import * as THREE from "three";
import { useEffect, useRef } from "react";
import { readPlaybackPreferences, type PlaybackPreferences } from "./playbackPreferences";
import { SongJourney } from "./songJourney";
import styles from "./SignalVisualizer.module.css";

type Color = [number, number, number];
const SAMPLES = 256;
// Tunnel cross-sections a scene can take: 0 is a circle, positive values are
// polygons with that many sides, negative values are blooms with that many petals.
const SHAPES = [0, 6, -4, 8, -6, 5];
const fragmentShader = `
  uniform vec2 resolution;
  uniform sampler2D waveform;
  uniform vec3 colorA, colorB, colorC;
  uniform float travel, drive, bass, mid, treble, pulse, beatPhase, anticipation, impact, shift;
  uniform float sidesFrom, sidesTo, shapeBlend, twist, progress, mode, opacity;
  varying vec2 vUv;
  const float PI = 3.14159265;
  // Radius scale for a cross-section along an angle: 1 for a circle, a regular
  // polygon for positive sides, a bloom of petals for negative sides.
  float polygon(float angle, float sides) {
    float n = abs(sides);
    if (n < 2.5) return 1.0;
    float sector = 2.0 * PI / n;
    float edge = cos(PI / n) / cos(mod(angle + PI / 2.0, sector) - sector * .5);
    return sides > 0.0 ? 1.0 / edge : edge;
  }
  void main() {
    vec2 p = vUv - .5;
    p.x *= resolution.x / resolution.y;
    vec3 rgb = vec3(0.0);
    if (mode < .5) {
      // Oscilloscope: the trace takes the scene colours from left to right and
      // leaves fading echoes when a bigger section lands.
      float x = vUv.x;
      float sampleValue = texture2D(waveform, vec2(x, .5)).r * 2.0 - 1.0;
      float height = .1 + drive * .1 + anticipation * .05;
      vec3 trace = mix(colorA, colorB, smoothstep(.1, .9, x));
      float ends = smoothstep(0.0, .12, x) * smoothstep(0.0, .12, 1.0 - x);
      for (int echo = 0; echo < 3; echo++) {
        float e = float(echo);
        float offset = e * (.035 + impact * .05);
        float y = sampleValue * height * (1.0 - e * .18);
        float d = min(abs(vUv.y - .5 - y - offset), abs(vUv.y - .5 - y + offset));
        float aa = max(fwidth(vUv.y - y), 1.0 / resolution.y);
        float core = 1.0 - smoothstep(0.0, aa * (1.3 + drive), d);
        float halo = exp(-d * resolution.y * (.2 - drive * .08));
        float weight = e < .5 ? 1.0 : (.22 + impact * .5) * (1.0 - e * .3);
        rgb += mix(trace, colorC, e * .35) * (core * .55 + halo * (.14 + pulse * .12)) * weight;
      }
      // A faint mirrored floor reflection.
      float mirror = abs(vUv.y - .5 + sampleValue * height * .6 + .26);
      rgb += trace * exp(-mirror * resolution.y * .08) * .05 * (.4 + drive);
      rgb *= ends * (.55 + drive * .55);
    } else {
      float radius = length(p * vec2(1.0, 1.1));
      float angle = atan(p.y, p.x);
      // Rings twist as they recede; the scene sets how much.
      float depthHint = -log(max(radius, .02));
      float turned = angle + depthHint * twist + travel * twist * .15;
      float shape = mix(polygon(turned, sidesFrom), polygon(turned, sidesTo), shapeBlend);
      float ripple = sin(angle * 3.0 + travel * .9) * mid * .02 + sin(angle * 7.0 - travel * .6) * treble * .008;
      float swell = 1.0 + bass * .05 + pulse * .035 + impact * .08 + ripple;
      // A build-up stretches the rings apart, as if the tunnel were accelerating.
      float spacing = 3.2 - anticipation * 1.4 + impact * .6;
      float depth = -log(max(radius * shape / swell, .02)) * spacing + travel;
      float ring = abs(fract(depth) - .5);
      float aa = max(fwidth(depth), .006);
      float line = 1.0 - smoothstep(.01, .01 + aa * 1.2, ring);
      float halo = exp(-ring * (26.0 - drive * 10.0));
      float aperture = smoothstep(.09, .3, radius);
      float outer = 1.0 - smoothstep(.6, 1.2, radius);
      // Alternate the scene colours along the tunnel, with a slow drift.
      float index = floor(depth);
      float alternate = .5 + .5 * sin(index * 1.3 + travel * .2);
      vec3 ringColor = mix(colorA, colorB, alternate);
      // Beats flash the nearest rings; the flash eases inward with the beat phase.
      float near = smoothstep(.22, .75, radius);
      float beatFlash = pulse * near * (1.0 - beatPhase * .6);
      float light = .16 + drive * .42 + beatFlash * .7;
      rgb += ringColor * (line * light + halo * (.05 + drive * .1 + treble * .08));
      // Wall panels between rings, lit by the treble.
      float panels = pow(.5 + .5 * cos(turned * max(3.0, abs(sidesTo)) + index * 2.1), 6.0);
      rgb += colorC * panels * halo * (.03 + treble * .14) * (.5 + drive);
      // Warp streaks pull toward the centre while a build-up gathers.
      float streakAngle = fract(angle / (2.0 * PI) * 48.0 + floor(depth * .5) * .37);
      float streak = exp(-abs(streakAngle - .5) * 40.0) * smoothstep(.12, .5, radius) * fract(depth * .5);
      rgb += mix(colorC, vec3(1.0), .35) * streak * anticipation * .5;
      // The impact: a bright shock ring racing outward.
      float shock = exp(-pow((radius - (1.0 - impact) * 1.1) * 9.0, 2.0)) * impact;
      rgb += mix(colorA, vec3(1.0), .45) * shock * .9;
      rgb *= aperture * outer;
      // A far light that grows as the song goes on: the end of the journey.
      rgb += colorC * exp(-radius * radius * 90.0) * (.05 + progress * .12) * (.6 + drive * .4);
    }
    // Soft roll-off keeps hue when lights overlap.
    rgb = rgb / (1.0 + rgb * .6);
    gl_FragColor = vec4(rgb, opacity);
  }
`;

/** One GPU draw call for the scope or the tunnel, both moving through the song's journey. */
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
    const uniforms = {
      waveform: { value: texture },
      resolution: { value: new THREE.Vector2(1, 1) },
      colorA: { value: new THREE.Vector3(0.3, 0.7, 0.65) },
      colorB: { value: new THREE.Vector3(0.5, 0.4, 0.8) },
      colorC: { value: new THREE.Vector3(0.6, 0.8, 1) },
      mode: { value: 0 },
      travel: { value: 0 },
      drive: { value: 0 },
      opacity: { value: 1 },
      bass: { value: 0 },
      mid: { value: 0 },
      treble: { value: 0 },
      pulse: { value: 0 },
      beatPhase: { value: 0 },
      anticipation: { value: 0 },
      impact: { value: 0 },
      shift: { value: 0 },
      progress: { value: 0 },
      sidesFrom: { value: 0 },
      sidesTo: { value: 0 },
      shapeBlend: { value: 1 },
      twist: { value: 0 },
    };
    const material = new THREE.ShaderMaterial({
      depthTest: false,
      depthWrite: false,
      uniforms,
      vertexShader: "varying vec2 vUv; void main(){vUv=uv;gl_Position=vec4(position.xy,0.0,1.0);}",
      fragmentShader,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.frustumCulled = false;
    scene.add(mesh);
    const journey = new SongJourney();
    let palette: Color[] = [
      [0.3, 0.7, 0.65],
      [0.5, 0.4, 0.8],
      [0.6, 0.8, 1],
    ];
    let frame = 0,
      lastFrame = 0,
      active = false,
      failed = false;
    let targetBass = 0,
      targetMid = 0,
      targetTreble = 0,
      lastAudio = -Infinity;
    const resize = () => {
      if (!renderer) return;
      const bounds = canvas.getBoundingClientRect();
      renderer.setPixelRatio(Math.min(1.5, window.devicePixelRatio || 1));
      renderer.setSize(Math.max(1, bounds.width), Math.max(1, bounds.height), false);
      renderer.getDrawingBufferSize(uniforms.resolution.value);
    };
    const draw = (now: number) => {
      if (!active || !renderer) return;
      frame = requestAnimationFrame(draw);
      const interval =
        preferences.waveFrameRate === "uncapped" ? 0 : 1000 / Number(preferences.waveFrameRate);
      if (now - lastFrame < interval) return;
      const dt = Math.min(0.05, (now - lastFrame) / 1000 || 0.016);
      lastFrame = now;
      const audible = now - lastAudio < 700;
      const rate =
        preferences.animationSpeed === "slow"
          ? 0.65
          : preferences.animationSpeed === "fast"
            ? 1.45
            : 1;
      journey.step(dt, rate, now / 1000);
      for (const [name, target] of [
        ["bass", targetBass],
        ["mid", targetMid],
        ["treble", targetTreble],
      ] as const) {
        const current = uniforms[name].value,
          next = audible ? target : 0;
        // Fast attack preserves beats; slower release avoids strobing.
        uniforms[name].value += (next - current) * (1 - Math.exp(-dt * (next > current ? 18 : 5)));
      }
      uniforms.travel.value = journey.travel * 1.6;
      uniforms.drive.value = journey.drive;
      uniforms.pulse.value = journey.beatPulse * preferences.bassReactivity;
      uniforms.beatPhase.value = journey.beatPhase;
      uniforms.anticipation.value = journey.anticipation;
      uniforms.impact.value = journey.impact;
      uniforms.shift.value = journey.shift;
      uniforms.progress.value = journey.progress;
      const blend = journey.sceneBlend * journey.sceneBlend * (3 - 2 * journey.sceneBlend);
      uniforms.sidesFrom.value = SHAPES[journey.previousScene % SHAPES.length];
      uniforms.sidesTo.value = SHAPES[journey.scene % SHAPES.length];
      uniforms.shapeBlend.value = blend;
      const twistFor = (scene: number) => [0, 0.25, -0.18, 0.4, -0.3, 0.12][scene % 6];
      uniforms.twist.value =
        twistFor(journey.previousScene) +
        (twistFor(journey.scene) - twistFor(journey.previousScene)) * blend;
      for (const [name, slot] of [
        ["colorA", 0],
        ["colorB", 1],
        ["colorC", 2],
      ] as const) {
        const color = journey.color(palette, slot);
        uniforms[name].value.lerp(new THREE.Vector3(...color), 1 - Math.exp(-dt * 3));
      }
      if (!audible) {
        for (let i = 0; i < SAMPLES; i++)
          samples[i] = Math.round(samples[i] + (128 - samples[i]) * Math.min(1, dt * 8));
        texture.needsUpdate = true;
      }
      renderer.render(scene, camera);
    };
    const sync = () => {
      const next =
        !failed &&
        preferences.wavesEnabled &&
        ["oscilloscope", "void"].includes(preferences.backdropPreset) &&
        !compact.matches &&
        !reduced.matches &&
        !document.hidden;
      canvas.style.display = next ? "block" : "none";
      if (next && !renderer) {
        try {
          renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: false });
          resize();
        } catch {
          failed = true;
          canvas.style.display = "none";
          return;
        }
      }
      uniforms.mode.value = preferences.backdropPreset === "void" ? 1 : 0;
      if (next === active) return;
      active = next;
      cancelAnimationFrame(frame);
      if (active) {
        lastFrame = performance.now();
        frame = requestAnimationFrame(draw);
      }
    };
    const receivePreferences = (event: Event) => {
      preferences = (event as CustomEvent<PlaybackPreferences>).detail;
      sync();
    };
    const receiveAudio = (event: Event) => {
      const detail = (event as CustomEvent<VisualFrame>).detail;
      journey.receive(detail, preferences);
      if (!detail.active) return;
      lastAudio = performance.now();
      targetBass = Math.min(1, detail.bass * preferences.bassReactivity * 1.4);
      targetMid = Math.min(1, detail.mid * preferences.vocalReactivity * 1.5);
      targetTreble = Math.min(1, detail.treble * preferences.trebleReactivity * 1.8);
      if (!active || preferences.backdropPreset !== "oscilloscope") return;
      const bins = detail.waveform;
      for (let i = 0; i < SAMPLES; i++) {
        const start = Math.floor((i * bins.length) / SAMPLES);
        const end = Math.min(
          bins.length,
          Math.max(start + 1, Math.floor(((i + 1) * bins.length) / SAMPLES)),
        );
        let sum = 0;
        for (let j = start; j < end; j++) sum += bins[j];
        samples[i] = end > start ? Math.round((sum / (end - start) + 1) * 127.5) : 128;
      }
      texture.needsUpdate = true;
    };
    const receivePalette = (event: Event) => {
      const { palette: next } = (event as CustomEvent<{ palette: TrackPalette | null }>).detail;
      if (next) palette = next.trails?.length >= 3 ? next.trails : next.waves;
    };
    const reset = () => {
      samples.fill(128);
      texture.needsUpdate = true;
      targetBass = targetMid = targetTreble = 0;
      lastAudio = -Infinity;
      journey.reset();
      for (const name of [
        "drive",
        "bass",
        "mid",
        "treble",
        "pulse",
        "impact",
        "anticipation",
      ] as const)
        uniforms[name].value = 0;
    };
    const events: [string, EventListener][] = [
      ["echora:playback-preferences", receivePreferences],
      ["echora:visual-frame", receiveAudio],
      ["echora:track-palette", receivePalette],
      ["echora:track-change", reset],
      ["resize", resize],
    ];
    events.forEach(([name, handler]) => window.addEventListener(name, handler));
    compact.addEventListener("change", sync);
    reduced.addEventListener("change", sync);
    document.addEventListener("visibilitychange", sync);
    sync();
    return () => {
      cancelAnimationFrame(frame);
      events.forEach(([name, handler]) => window.removeEventListener(name, handler));
      compact.removeEventListener("change", sync);
      reduced.removeEventListener("change", sync);
      document.removeEventListener("visibilitychange", sync);
      geometry.dispose();
      material.dispose();
      texture.dispose();
      renderer?.dispose();
    };
  }, []);
  return <canvas ref={ref} className={styles.signal} aria-hidden="true" />;
}
