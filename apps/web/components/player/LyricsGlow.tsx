"use client";

import * as THREE from "three";
import { useEffect, useRef, type RefObject } from "react";
import styles from "./LyricsGlow.module.css";

/** Text remains in the DOM. This canvas only paints light behind its bounds. */
export default function LyricsGlow({
  container,
  playing,
}: {
  container: RefObject<HTMLElement | null>;
  playing: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const playingRef = useRef(playing);
  useEffect(() => {
    playingRef.current = playing;
  }, [playing]);
  useEffect(() => {
    const canvas = canvasRef.current;
    const root = container.current;
    if (!canvas || !root) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (reduced.matches) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: false });
    } catch {
      return;
    }
    const scene = new THREE.Scene();
    const camera = new THREE.Camera();
    // Two groups of eight light spots: the singing line, and the line it just left,
    // which fades out in place while the new one fades in.
    const SPOTS = 8;
    const spots = Array.from({ length: SPOTS * 2 }, () => new THREE.Vector4(0, 0, 1, 1));
    const weights = new Float32Array(SPOTS * 2);
    const material = new THREE.ShaderMaterial({
      transparent: true,
      depthWrite: false,
      depthTest: false,
      uniforms: {
        spots: { value: spots },
        weights: { value: weights },
        resolution: { value: new THREE.Vector2(1, 1) },
        clock: { value: 0 },
        tint: { value: new THREE.Vector3(0.3, 0.8, 0.72) },
      },
      vertexShader: "varying vec2 vUv;void main(){vUv=uv;gl_Position=vec4(position.xy,0.0,1.0);}",
      fragmentShader: `
        varying vec2 vUv;
        uniform vec4 spots[${SPOTS * 2}];
        uniform float weights[${SPOTS * 2}];
        uniform vec2 resolution;
        uniform float clock;
        uniform vec3 tint;
        void main() {
          vec2 pixel = vec2(vUv.x, 1.0-vUv.y) * resolution;
          float glow = 0.0;
          for(int i=0;i<${SPOTS * 2};i++) {
            if(weights[i]<=0.001) continue;
            vec4 spot=spots[i];
            vec2 drift=vec2(sin(clock*.8+float(i)),cos(clock*.65+float(i)))*1.5;
            vec2 d=(pixel-spot.xy-drift)/spot.zw;
            glow += weights[i]*exp(-dot(d,d)*2.5);
          }
          gl_FragColor=vec4(tint,min(.12,glow*.08));
        }
      `,
    });
    const geometry = new THREE.PlaneGeometry(2, 2);
    const mesh = new THREE.Mesh(geometry, material);
    mesh.frustumCulled = false;
    scene.add(mesh);
    // Spots live relative to their lyric line, so scrolling carries them with the text
    // exactly; only movement within a line (word to word) glides.
    type Group = {
      line: HTMLElement | null;
      rel: THREE.Vector4[];
      target: THREE.Vector4[];
      count: number;
      weight: number;
    };
    const group = (): Group => ({
      line: null,
      count: 0,
      weight: 0,
      rel: Array.from({ length: SPOTS }, () => new THREE.Vector4(0, 0, 1, 1)),
      target: Array.from({ length: SPOTS }, () => new THREE.Vector4(0, 0, 1, 1)),
    });
    let current = group(),
      previous = group();
    let frame = 0,
      last = 0,
      lastTint = 0,
      visible = false;
    // Text boxes span the font's full ascent and descent, whose middle sits above the letters'
    // visual middle. Measure the real glyphs once per font and text, and move the glow down by the gap.
    const metrics = document.createElement("canvas").getContext("2d");
    const offsets = new Map<string, number>();
    const visualOffset = (element: HTMLElement) => {
      if (!metrics) return 0;
      const style = getComputedStyle(element);
      const text = (element.textContent || "").trim().slice(0, 80);
      const key = `${style.font}|${text}`;
      const known = offsets.get(key);
      if (known !== undefined) return known;
      metrics.font = style.font;
      const glyphs = metrics.measureText(text || "Hx");
      const offset =
        (glyphs.fontBoundingBoxAscent -
          glyphs.fontBoundingBoxDescent -
          (glyphs.actualBoundingBoxAscent - glyphs.actualBoundingBoxDescent)) /
        2;
      const value = Number.isFinite(offset) ? Math.max(-12, Math.min(12, offset)) : 0;
      if (offsets.size > 200) offsets.clear();
      offsets.set(key, value);
      return value;
    };
    const resize = () => {
      const box = root.getBoundingClientRect();
      renderer.setPixelRatio(1);
      renderer.setSize(Math.max(1, box.width), Math.max(1, box.height), false);
      material.uniforms.resolution.value.set(box.width, box.height);
    };
    const measure = () => {
      const active = root.querySelectorAll<HTMLElement>('[data-lyric-singing="true"]');
      let boxes: DOMRect[] = [];
      for (const element of active) boxes.push(...Array.from(element.getClientRects()));
      boxes = boxes.filter((box) => box.width > 0 && box.height > 0).slice(0, SPOTS);
      // Only timed karaoke fragments emit light. Rests intentionally have no glow.
      visible = boxes.length > 0;
      if (!visible) return;
      const line = active[0]?.closest<HTMLElement>("[data-index]") ?? null;
      if (!line) {
        visible = false;
        return;
      }
      const anchor = line.getBoundingClientRect();
      const textElement = active[0]?.parentElement;
      const shift = textElement ? visualOffset(textElement) : 0;
      if (line !== current.line) {
        // A new line: the old glow keeps fading on its own line; the new one starts in place.
        // Returning to the line still fading out (a quick seek back) resumes its glow.
        const returning = line === previous.line;
        [previous, current] = [current, previous];
        if (!returning) {
          current.line = line;
          current.weight = 0;
        }
      }
      current.count = boxes.length;
      boxes.forEach((box, index) =>
        current.target[index].set(
          box.x - anchor.x + box.width / 2,
          box.y - anchor.y + box.height / 2 + shift,
          Math.min(180, box.width / 2 + 24),
          box.height / 2 + 22,
        ),
      );
      if (current.weight < 0.02)
        current.target.forEach((target, index) => current.rel[index].copy(target));
    };
    const place = (from: Group, offset: number, origin: DOMRect) => {
      const anchor = from.line?.isConnected ? from.line.getBoundingClientRect() : null;
      for (let index = 0; index < SPOTS; index++) {
        const lit = anchor && index < from.count ? from.weight : 0;
        weights[offset + index] = lit;
        if (!lit || !anchor) continue;
        const rel = from.rel[index];
        spots[offset + index].set(
          anchor.x - origin.x + rel.x,
          anchor.y - origin.y + rel.y,
          rel.z,
          rel.w,
        );
      }
    };
    const draw = (now: number) => {
      frame = requestAnimationFrame(draw);
      if (document.hidden || reduced.matches) {
        last = now;
        return;
      }
      const dt = Math.min(0.05, (now - last) / 1000 || 0.016);
      last = now;
      measure();
      if (now - lastTint >= 500) {
        lastTint = now;
        const color = getComputedStyle(root)
          .getPropertyValue("--accent-rgb")
          .trim()
          .split(/\s+/)
          .map(Number);
        if (color.length === 3 && color.every(Number.isFinite))
          material.uniforms.tint.value.set(
            ...(color.map((value) => value / 255) as [number, number, number]),
          );
      }
      const playing = playingRef.current;
      current.weight += ((visible && playing ? 1 : 0) - current.weight) * (1 - Math.exp(-dt * 10));
      previous.weight += (0 - previous.weight) * (1 - Math.exp(-dt * 12));
      current.rel.forEach((rel, index) => rel.lerp(current.target[index], 1 - Math.exp(-dt * 16)));
      const origin = root.getBoundingClientRect();
      place(current, 0, origin);
      place(previous, SPOTS, origin);
      material.uniforms.clock.value += dt;
      renderer.render(scene, camera);
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(root);
    frame = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      geometry.dispose();
      material.dispose();
      renderer.dispose();
    };
  }, [container]);
  return <canvas ref={canvasRef} className={styles.glow} aria-hidden="true" />;
}
