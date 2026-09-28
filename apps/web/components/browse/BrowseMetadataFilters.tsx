"use client";
import { useEffect, useState } from "react";
import styles from "./BrowseMetadataFilters.module.css";
export type MetadataFilters = { vocals: string; language: string; lyrics: string; translation: string; genre: string; year_from: string; year_to: string };
export const emptyMetadataFilters: MetadataFilters = { vocals: "", language: "", lyrics: "", translation: "", genre: "", year_from: "", year_to: "" };
type Facet = { name: string; tracks: number };
type Options = { language: Facet[]; genre: Facet[]; translation: Facet[] };
export default function BrowseMetadataFilters({ value, onChange }: { value: MetadataFilters; onChange: (next: MetadataFilters) => void }) {
  const [options, setOptions] = useState<Options>({ language: [], genre: [], translation: [] });
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const abort = new AbortController();
    fetch("/analysis/library/filter-options", { signal: abort.signal }).then(async response => {
      if (!response.ok) throw new Error();
      setOptions(await response.json()); setError("");
    }).catch(() => { if (!abort.signal.aborted) setError("Could not load filter options"); });
    return () => abort.abort();
  }, [retry]);
  const set = (key: keyof MetadataFilters, next: string) => onChange({ ...value, [key]: next });
  const count = Object.values(value).filter(Boolean).length;
  return <details className={styles.filters}><summary>Track details {count > 0 && <span>{count} active</span>}</summary><div className={styles.body}>
    <label>Vocals<select value={value.vocals} onChange={e => set("vocals", e.target.value)}><option value="">Any vocals</option><option value="instrumental">Instrumental</option><option value="vocal">Vocal tracks</option><option value="female">Female vocal evidence</option><option value="male">Male vocal evidence</option><option value="unknown">Not classified</option></select></label>
    <fieldset><legend>Lyrics language</legend>{options.language.map(item => <label className={styles.language} key={item.name}><input type="checkbox" checked={value.language.split(",").includes(item.name)} onChange={e => set("language", (e.target.checked ? [...value.language.split(",").filter(Boolean), item.name] : value.language.split(",").filter(name => name !== item.name)).join(","))} />{item.name === "unknown" ? "Unknown" : item.name}<span>{item.tracks}</span></label>)}</fieldset>
    <label>Lyrics<select value={value.lyrics} onChange={e => set("lyrics", e.target.value)}><option value="">Any lyrics status</option><option value="available">Available</option><option value="missing">Missing text</option><option value="ai">AI-generated</option></select></label>
    <label>Translated into<select value={value.translation} onChange={e => set("translation", e.target.value)}><option value="">Any translation status</option>{options.translation.map(item => <option key={item.name} value={item.name}>{item.name} ({item.tracks})</option>)}</select></label>
    <label>Genre<select value={value.genre} onChange={e => set("genre", e.target.value)}><option value="">All genres</option>{options.genre.map(item => <option key={item.name} value={item.name}>{item.name} ({item.tracks})</option>)}</select></label>
    <div className={styles.years}><label>Year from<input type="number" min="0" max="9999" value={value.year_from} onChange={e => set("year_from", e.target.value)} /></label><label>Year to<input type="number" min="0" max="9999" value={value.year_to} onChange={e => set("year_to", e.target.value)} /></label></div>
    {error && <button type="button" onClick={() => setRetry(n => n + 1)}>{error}. Retry</button>}
    <small>Counts cover your library, before filtering.</small>
    <button type="button" disabled={!count} onClick={() => onChange({ ...emptyMetadataFilters })}>Clear track details</button>
  </div></details>;
}
