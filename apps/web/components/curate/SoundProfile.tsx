"use client";

import { PointerEvent, useRef } from "react";
import styles from "./SoundProfile.module.css";

export const SOUND_PROFILE_AXES = [
  ["pace", "Pace"], ["energy", "Energy"], ["brightness", "Brightness"],
  ["motion", "Motion"], ["vocals", "Vocals"], ["dynamics", "Dynamics"],
] as const;

export type SoundProfileValues = Partial<Record<(typeof SOUND_PROFILE_AXES)[number][0], number>>;
export type SoundProfilePreset = { name: string; values: SoundProfileValues };

export const SOUND_PROFILE_PRESETS: SoundProfilePreset[] = [
  { name: "Still", values: { pace: .25, energy: .2, brightness: .3, motion: .2, vocals: .25, dynamics: .45 } },
  { name: "Warm", values: { pace: .45, energy: .42, brightness: .28, motion: .35, vocals: .55, dynamics: .6 } },
  { name: "Driving", values: { pace: .75, energy: .72, brightness: .58, motion: .7, vocals: .5, dynamics: .5 } },
  { name: "Club", values: { pace: .82, energy: .86, brightness: .7, motion: .8, vocals: .32, dynamics: .38 } },
  { name: "Low vocals", values: { pace: .48, energy: .5, brightness: .48, motion: .45, vocals: .25, dynamics: .58 } },
  { name: "High vocals", values: { pace: .5, energy: .52, brightness: .48, motion: .42, vocals: .9, dynamics: .55 } },
];

const center = 130;
const radius = 84;
const angle = (index: number) => -Math.PI / 2 + index * Math.PI * 2 / SOUND_PROFILE_AXES.length;
const point = (index: number, value: number) => [center + Math.cos(angle(index)) * radius * value, center + Math.sin(angle(index)) * radius * value] as const;

export default function SoundProfile({ value, onChange, instrumentalOnly, onInstrumentalOnlyChange }: { value: SoundProfileValues; onChange: (value: SoundProfileValues) => void; instrumentalOnly: boolean; onInstrumentalOnlyChange: (value: boolean) => void }) {
  const svg = useRef<SVGSVGElement>(null);
  const values = SOUND_PROFILE_AXES.map(([key]) => value[key] ?? .5);
  const polygon = values.map((axisValue, index) => point(index, axisValue).join(",")).join(" ");
  const setAxis = (index: number, next: number) => {
    const base = Object.keys(value).length ? value : Object.fromEntries(SOUND_PROFILE_AXES.map(([key]) => [key, .5])) as SoundProfileValues;
    onChange({ ...base, [SOUND_PROFILE_AXES[index][0]]: Math.round(Math.max(0, Math.min(1, next)) * 100) / 100 });
  };
  const drag = (event: PointerEvent<SVGSVGElement>, index: number) => {
    const bounds = svg.current?.getBoundingClientRect();
    if (!bounds) return;
    const x = (event.clientX - bounds.left) / bounds.width * 260;
    const y = (event.clientY - bounds.top) / bounds.height * 260;
    const projected = ((x - center) * Math.cos(angle(index)) + (y - center) * Math.sin(angle(index))) / radius;
    setAxis(index, projected);
  };
  return <section className={styles.profile} aria-labelledby="sound-profile-title">
    <header><div><strong id="sound-profile-title">Sound shape</strong><small>Drag each point toward the sound you want. Values are relative to your library.</small></div><button type="button" onClick={() => { onChange({}); onInstrumentalOnlyChange(false); }}>Reset</button></header>
    <div className={styles.chartWrap}>
      <svg ref={svg} className={styles.chart} viewBox="0 0 260 260" role="img" aria-label="Six-axis sound profile: pace, energy, brightness, motion, vocals, and dynamics">
        {[.25, .5, .75, 1].map(level => <polygon key={level} className={styles.ring} points={SOUND_PROFILE_AXES.map((_, index) => point(index, level).join(",")).join(" ")} />)}
        {SOUND_PROFILE_AXES.map((_, index) => { const [x, y] = point(index, 1); return <line key={index} x1={center} y1={center} x2={x} y2={y} className={styles.spoke} />; })}
        <polygon className={styles.shape} points={polygon} />
        {values.map((axisValue, index) => { const [x, y] = point(index, axisValue); return <circle key={index} className={styles.handle} cx={x} cy={y} r="8" data-axis={index} onPointerDown={event => { event.currentTarget.setPointerCapture(event.pointerId); drag(event as unknown as PointerEvent<SVGSVGElement>, index); }} onPointerMove={event => { if (event.currentTarget.hasPointerCapture(event.pointerId)) drag(event as unknown as PointerEvent<SVGSVGElement>, index); }} />; })}
      </svg>
      {SOUND_PROFILE_AXES.map(([key, label], index) => { const [x, y] = point(index, 1.18); return <span key={key} className={styles.axisLabel} style={{ left: `${x / 2.6}%`, top: `${y / 2.6}%` }}>{label}</span>; })}
    </div>
    <div className={styles.axisControls}>{SOUND_PROFILE_AXES.map(([key, label], index) => <label key={key}><span>{label}</span><input type="range" min="0" max="100" value={Math.round(values[index] * 100)} onChange={event => setAxis(index, Number(event.target.value) / 100)} /><output>{Math.round(values[index] * 100)}</output></label>)}</div>
    <div className={styles.presets} aria-label="Sound shape presets">{SOUND_PROFILE_PRESETS.map(preset => <button type="button" key={preset.name} onClick={() => onChange(preset.values)}>{preset.name}</button>)}</div>
    <div className={styles.instrumentalOnly}><div><strong>Instrumental only</strong><small>Require tracks classified as instrumental. Use Low vocals when you want songs with softer or less prominent vocals.</small></div><button type="button" aria-pressed={instrumentalOnly} onClick={() => onInstrumentalOnlyChange(!instrumentalOnly)}>{instrumentalOnly ? "ON" : "OFF"}</button></div>
  </section>;
}
