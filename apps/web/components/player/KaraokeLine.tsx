"use client";

import { useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { fragmentProgress, lyricWordIsRtl, type LyricFragment } from "./lyricWords";
import styles from "./KaraokeLine.module.css";

type Box = { x: number; y: number; width: number; height: number };
type Geometry = { width: number; height: number; fragments: Box[][]; source: LyricFragment[] };

type Props = { fragments: LyricFragment[]; now: number; active: boolean; highlightStyle: "lava" | "syllable" };

/** Native text layout owns shaping, wrapping, punctuation, and bidirectional runs. */
export default function KaraokeLine({ fragments, now, active, highlightStyle }: Props) {
  const root = useRef<HTMLSpanElement>(null);
  const base = useRef<HTMLSpanElement>(null);
  const [geometry, setGeometry] = useState<Geometry | null>(null);
  const text = fragments.map(fragment => fragment.text).join("");
  useLayoutEffect(() => {
    const element = root.current;
    const node = base.current?.firstChild;
    if (!element || !node) return;
    let disposed = false;
    const measure = () => {
      if (disposed) return;
      const bounds = element.getBoundingClientRect();
      if (!bounds.width || !bounds.height) return;
      // Ignore entrance-animation transforms when converting viewport bounds to local pixels.
      const scaleX = bounds.width / element.offsetWidth;
      const scaleY = bounds.height / element.offsetHeight;
      let offset = 0;
      const boxes = fragments.map(fragment => {
        const range = document.createRange();
        range.setStart(node, offset);
        offset += fragment.text.length;
        range.setEnd(node, offset);
        if (!fragment.text.trim()) return [];
        return Array.from(range.getClientRects()).map(box => ({
          x: (box.left - bounds.left) / scaleX, y: (box.top - bounds.top) / scaleY,
          width: box.width / scaleX, height: box.height / scaleY,
        }));
      });
      setGeometry({ width: element.offsetWidth, height: element.offsetHeight, fragments: boxes, source: fragments });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    void document.fonts?.ready.then(measure);
    return () => { disposed = true; observer.disconnect(); };
  }, [fragments]);

  const paths = (geometry?.source === fragments ? geometry.fragments : []).flatMap((boxes, index) => {
    const fragment = fragments[index];
    const fragmentRtl = lyricWordIsRtl(fragment.text);
    const progress = now >= fragment.syllable.end_ms ? 100
      : active && now >= fragment.syllable.start_ms
        ? highlightStyle === "syllable" ? 100 : fragmentProgress(now, fragment) : 0;
    let remaining = boxes.reduce((sum, box) => sum + box.width, 0) * progress / 100;
    return boxes.map(box => {
      const fill = Math.max(0, Math.min(box.width, remaining));
      remaining -= box.width;
      if (fill <= 0) return "";
      const top = box.y - 2, bottom = box.y + box.height + 2;
      const side = fragmentRtl ? box.x + box.width : box.x;
      const edge = side + (fragmentRtl ? -fill : fill);
      const amplitude = Math.min(5, fill * .15, (box.width - fill) * .15);
      const boundary = Array.from({ length: 13 }, (_, point) => {
        const y = top + (bottom - top) * point / 12;
        const x = edge + Math.sin(point / 12 * Math.PI * 2 + now / 320 + index * .8) * amplitude;
        return `L${x.toFixed(2)},${y.toFixed(2)}`;
      }).join(" ");
      return `<path fill="white" d="M${side},${top} ${boundary} L${side},${bottom} Z"/>`;
    });
  }).join("") || "";
  const mask = geometry && paths ? `url("data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${geometry.width} ${geometry.height}">${paths}</svg>`)}")` : "none";
  const paint: CSSProperties = { maskImage: mask, WebkitMaskImage: mask, visibility: paths ? "visible" : "hidden" };

  return <span ref={root} dir="auto" className={styles.line}>
    <span ref={base}>{text}</span>
    <span className={styles.paint} aria-hidden="true" style={paint}>{text}</span>
    {active && geometry?.source === fragments && geometry.fragments.flatMap((boxes, index) => {
      const { syllable } = fragments[index];
      if (now < syllable.start_ms || now >= syllable.end_ms) return [];
      return boxes.map((box, part) => <span key={`${index}-${part}`} aria-hidden="true" data-lyric-singing="true" className={styles.glowTarget}
        style={{ left: box.x, top: box.y, width: box.width, height: box.height }} />);
    })}
  </span>;
}
