"use client";

import { useLayoutEffect, useRef, type ReactNode } from "react";
import styles from "./AnimatedLyrics.module.css";

type Position = { center: number; scale: number; opacity: number };
const matrixFor = (element: Element) => {
  const transform = getComputedStyle(element).transform;
  return new DOMMatrixReadOnly(transform === "none" ? undefined : transform);
};

/** Move rows vertically; scale text independently so bilingual columns stay aligned. */
export default function AnimatedLyrics({ children, className, motionKey }: { children: ReactNode; className: string; motionKey: string }) {
  const ref = useRef<HTMLElement>(null);
  const positions = useRef(new Map<string, Position>());
  const animations = useRef(new Map<string, Animation[]>());

  useLayoutEffect(() => {
    const root = ref.current;
    if (!root) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const next = new Map<string, Position>();
    const measurements = Array.from(root.querySelectorAll<HTMLButtonElement>("button[data-line-id]")).map(element => {
      const id = element.dataset.lineId!;
      const text = Array.from(element.children).filter((child): child is HTMLElement => child instanceof HTMLElement);
      const previous = positions.current.get(id);
      const origin = previous ? {
        center: previous.center + matrixFor(element).m42,
        scale: text[0] ? matrixFor(text[0]).a : 1,
        opacity: Number(getComputedStyle(element).opacity),
      } : undefined;
      for (const animation of animations.current.get(id) || []) animation.cancel();
      const rect = element.getBoundingClientRect();
      const target = { center: rect.top + rect.height / 2, scale: text[0] ? matrixFor(text[0]).a : 1, opacity: Number(getComputedStyle(element).opacity) };
      next.set(id, target);
      return { element, text, id, origin, target };
    });
    for (const { element, text, id, origin, target } of measurements) {
      if (reduced || !positions.current.size) continue;
      const start = origin || { ...target, center: target.center + 28, opacity: 0 };
      const options = { duration: 620, easing: "cubic-bezier(.22,.68,.2,1)" };
      const motion = element.animate([
        { transform: `translateY(${start.center - target.center}px)`, opacity: start.opacity },
        { transform: "translateY(0)", opacity: target.opacity },
      ], options);
      const scaling = text.map(child => child.animate([
        { transform: `scale(${start.scale})` },
        { transform: `scale(${target.scale})` },
      ], options));
      animations.current.set(id, [motion, ...scaling]);
    }
    for (const [id, motions] of animations.current) if (!next.has(id)) {
      for (const motion of motions) motion.cancel();
      animations.current.delete(id);
    }
    positions.current = next;
  }, [motionKey]);

  useLayoutEffect(() => () => { for (const motions of animations.current.values()) for (const motion of motions) motion.cancel(); }, []);

  return <aside ref={ref} className={`${className} ${styles.stage}`}>{children}</aside>;
}
