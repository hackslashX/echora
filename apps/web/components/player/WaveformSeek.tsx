"use client";

import { useMemo, type CSSProperties } from "react";
import { usePlayer } from "./PlayerProvider";
import styles from "./WaveformSeek.module.css";

const stamp = (seconds: number) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;

export default function WaveformSeek({ compact = false }: { compact?: boolean }) {
  const { track, waveform, duration, currentTime, seek } = usePlayer();
  const maximum = Number.isFinite(duration) && duration > 0 ? duration : 0;
  const position = Math.max(0, Math.min(Number.isFinite(currentTime) ? currentTime : 0, maximum));
  const progress = maximum ? position / maximum * 100 : 0;
  const path = useMemo(() => {
    if (!waveform?.length) return "";
    const count = Math.min(compact ? 100 : 200, waveform.length);
    return Array.from({ length: count }, (_, index) => {
      const start = Math.floor(index * waveform.length / count);
      const end = Math.floor((index + 1) * waveform.length / count);
      const height = Math.max(1, Math.max(...waveform.slice(start, end)) * 44);
      const x = index * 1000 / count;
      return `M${x},${(48 - height) / 2}h${1000 / count * .65}v${height}h-${1000 / count * .65}Z`;
    }).join(" ");
  }, [waveform, compact]);
  return <span className={`${styles.seek} ${compact ? styles.compact : ""}`} style={{ "--played": `${progress}%` } as CSSProperties}>
    {path ? <><svg viewBox="0 0 1000 48" preserveAspectRatio="none" aria-hidden="true"><path d={path} /></svg><svg className={styles.played} viewBox="0 0 1000 48" preserveAspectRatio="none" aria-hidden="true"><path d={path} /></svg></> : <span className={styles.fallback} aria-hidden="true" />}
    <input type="range" min={0} max={maximum} step={0.1} value={position} disabled={!track || !maximum} onChange={event => seek(Number(event.target.value))} aria-label="Seek" aria-valuetext={`${stamp(position)} of ${stamp(maximum)}`} />
  </span>;
}
