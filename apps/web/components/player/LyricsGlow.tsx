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
    const spots = Array.from({ length: 8 }, () => new THREE.Vector4(0, 0, 1, 1));
    const targets = spots.map((spot) => spot.clone());
    // Where the next line's glow goes while the current line's glow fades out.
    const nextTargets = spots.map((spot) => spot.clone());
    const material = new THREE.ShaderMaterial({
      transparent: true,
      depthWrite: false,
      depthTest: false,
      uniforms: {
        spots: { value: spots },
        count: { value: 0 },
        strength: { value: 0 },
        resolution: { value: new THREE.Vector2(1, 1) },
        clock: { value: 0 },
        tint: { value: new THREE.Vector3(0.3, 0.8, 0.72) },
      },
      vertexShader: "varying vec2 vUv;void main(){vUv=uv;gl_Position=vec4(position.xy,0.0,1.0);}",
      fragmentShader: `
        varying vec2 vUv;
        uniform vec4 spots[8];
        uniform int count;
        uniform vec2 resolution;
        uniform float strength;
        uniform float clock;
        uniform vec3 tint;
        void main() {
          vec2 pixel = vec2(vUv.x, 1.0-vUv.y) * resolution;
          float glow = 0.0;
          for(int i=0;i<8;i++) {
            if(i>=count) break;
            vec4 spot=spots[i];
            vec2 drift=vec2(sin(clock*.8+float(i)),cos(clock*.65+float(i)))*3.0;
            vec2 d=(pixel-spot.xy-drift)/spot.zw;
            glow += exp(-dot(d,d)*2.5);
          }
          gl_FragColor=vec4(tint,min(.12,glow*.08)*strength);
        }
      `,
    });
    const geometry = new THREE.PlaneGeometry(2, 2);
    const mesh = new THREE.Mesh(geometry, material);
    mesh.frustumCulled = false;
    scene.add(mesh);
    let frame = 0,
      last = 0,
      lastMeasure = 0,
      visible = false;
    // The lyric line that currently glows, and the line waiting for the glow to fade before it moves.
    let line = "",
      nextLine = "",
      nextCount = 0;
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
      const origin = root.getBoundingClientRect();
      let boxes: DOMRect[] = [];
      const active = root.querySelectorAll<HTMLElement>('[data-lyric-singing="true"]');
      for (const element of active) boxes.push(...Array.from(element.getClientRects()));
      boxes = boxes.filter((box) => box.width > 0 && box.height > 0).slice(0, 8);
      // Only timed karaoke fragments emit light. Rests intentionally have no glow.
      visible = boxes.length > 0;
      if (!visible) {
        nextLine = "";
        return;
      }
      const lineElement = active[0]?.closest<HTMLElement>("[data-index]");
      const singing = lineElement?.dataset.index ?? "";
      const textElement = active[0]?.parentElement;
      const shift = textElement ? visualOffset(textElement) : 0;
      const place = (into: THREE.Vector4[]) =>
        boxes.forEach((box, index) =>
          into[index].set(
            box.x - origin.x + box.width / 2,
            box.y - origin.y + box.height / 2 + shift,
            Math.min(180, box.width / 2 + 24),
            box.height / 2 + 22,
          ),
        );
      if (singing !== line && material.uniforms.strength.value > 0.03) {
        // A new line started while the old one still glows: fade out where it is, then move.
        nextLine = singing;
        nextCount = boxes.length;
        place(nextTargets);
      } else if (singing !== line) {
        // Nothing is lit, so the glow can appear on the new line directly.
        line = singing;
        nextLine = "";
        material.uniforms.count.value = boxes.length;
        place(targets);
        targets.forEach((target, index) => spots[index].copy(target));
      } else {
        // Words within a line glide.
        material.uniforms.count.value = boxes.length;
        place(targets);
      }
      const color = getComputedStyle(root)
        .getPropertyValue("--accent-rgb")
        .trim()
        .split(/\s+/)
        .map(Number);
      if (color.length === 3 && color.every(Number.isFinite))
        material.uniforms.tint.value.set(
          ...(color.map((value) => value / 255) as [number, number, number]),
        );
    };
    const draw = (now: number) => {
      frame = requestAnimationFrame(draw);
      if (document.hidden || reduced.matches || now - last < 1000 / 30) return;
      const dt = Math.min(0.05, (now - last) / 1000 || 0.033);
      last = now;
      if (now - lastMeasure >= 50) {
        measure();
        lastMeasure = now;
      }
      const fading = Boolean(nextLine);
      const strength = visible && playingRef.current && !fading ? 1 : 0;
      // Fading out before a line change is quicker than fading in, so the move feels prompt.
      material.uniforms.strength.value +=
        (strength - material.uniforms.strength.value) * (1 - Math.exp(-dt * (fading ? 24 : 10)));
      if (fading && material.uniforms.strength.value <= 0.03) {
        line = nextLine;
        nextLine = "";
        material.uniforms.count.value = nextCount;
        nextTargets.forEach((target, index) => {
          targets[index].copy(target);
          spots[index].copy(target);
        });
      }
      spots.forEach((spot, index) => spot.lerp(targets[index], 1 - Math.exp(-dt * 16)));
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
