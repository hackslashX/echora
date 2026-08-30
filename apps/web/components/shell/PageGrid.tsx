"use client";

import type { CSSProperties } from "react";
import { useEffect, useRef, useState } from "react";
import styles from "./PageGrid.module.css";
import { linePositions, type GridDefinition } from "./gridGeometry";

type Phase = "entering" | "idle" | "leaving";
type Line = { id: string; position: string; opacity: number };

function linesFor(weights: number[], fixed: number, prefix: string): Line[] {
  const values = linePositions(weights, fixed);
  return values.map((position, index) => ({ id: `${prefix}-${index < 2 ? `start-${index}` : index >= values.length - 2 ? `end-${values.length - index}` : `dynamic-${index - 2}`}`, position, opacity: 1 }));
}

function morph(oldLines: Line[], newLines: Line[], prefix: string): { from: Line[]; to: Line[] } {
  const oldDynamic = oldLines.filter(line => line.id.includes("dynamic"));
  const newDynamic = newLines.filter(line => line.id.includes("dynamic"));
  const fixed = newLines.filter(line => !line.id.includes("dynamic"));
  const count = Math.max(oldDynamic.length, newDynamic.length);
  const from: Line[] = [...fixed];
  const to: Line[] = [...fixed];
  for (let index = 0; index < count; index++) {
    const oldLine = oldDynamic[index];
    const newLine = newDynamic[index];
    const collapseLeft = index < count / 2;
    const edge = collapseLeft ? `${prefix === "v" ? 180 : 152}px` : `calc(100% - ${prefix === "v" ? 180 : 152}px)`;
    from.push({ id: `${prefix}-dynamic-${index}`, position: oldLine?.position || edge, opacity: oldLine ? 1 : 0 });
    to.push({ id: `${prefix}-dynamic-${index}`, position: newLine?.position || edge, opacity: newLine ? 1 : 0 });
  }
  return { from, to };
}

function style(axis: "left" | "top", line: Line, delay = 0): CSSProperties {
  return { [axis]: line.position, opacity: line.opacity, transitionDelay: `${delay}ms` };
}

export default function PageGrid({ columns, rows, phase }: GridDefinition & { phase: Phase }) {
  const previous = useRef<GridDefinition>({ columns, rows });
  const [vertical, setVertical] = useState(() => linesFor(columns, 180, "v"));
  const [horizontal, setHorizontal] = useState(() => linesFor(rows, 152, "h"));
  const signature = `${columns.join(",")}|${rows.join(",")}`;

  useEffect(() => {
    const oldSignature = `${previous.current.columns.join(",")}|${previous.current.rows.join(",")}`;
    if (oldSignature === signature) return;
    const verticalMorph = morph(linesFor(previous.current.columns, 180, "v"), linesFor(columns, 180, "v"), "v");
    const horizontalMorph = morph(linesFor(previous.current.rows, 152, "h"), linesFor(rows, 152, "h"), "h");
    setVertical(verticalMorph.from); setHorizontal(horizontalMorph.from);
    const frame = requestAnimationFrame(() => requestAnimationFrame(() => { setVertical(verticalMorph.to); setHorizontal(horizontalMorph.to); }));
    previous.current = { columns, rows };
    return () => cancelAnimationFrame(frame);
  }, [columns, rows, signature]);

  return <div className={`${styles.grid} ${styles[phase]}`} aria-hidden="true">
    {vertical.map(line => <i key={line.id} className={`${styles.line} ${styles.vertical}`} style={style("left", line)} />)}
    {horizontal.map(line => <i key={line.id} className={`${styles.line} ${styles.horizontal}`} style={style("top", line)} />)}
  </div>;
}
