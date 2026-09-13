"use client";

import { Search, X } from "lucide-react";
import { useEffect, useState } from "react";
import styles from "./TrackReferencePicker.module.css";

export type ReferenceTrack = { id: string; title: string; artist?: string; album?: string };

export default function TrackReferencePicker({ label, value, onChange, single = false }: {
  label: string;
  value: ReferenceTrack[];
  onChange: (tracks: ReferenceTrack[]) => void;
  single?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ReferenceTrack[]>([]);

  useEffect(() => {
    if (query.trim().length < 2) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      const params = new URLSearchParams({ q: query.trim(), limit: "8", offset: "0", sort_by: "name" });
      fetch(`/analysis/library/tracks?${params}`, { signal: controller.signal })
        .then(response => response.ok ? response.json() : Promise.reject(new Error("Search failed")))
        .then(body => setResults((body.tracks || []).filter((track: ReferenceTrack) => !value.some(item => item.id === track.id))))
        .catch(error => { if (error.name !== "AbortError") setResults([]); });
    }, 220);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [query, value]);

  function add(track: ReferenceTrack) {
    onChange(single ? [track] : [...value, track]);
    setQuery("");
    setResults([]);
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Backspace" && !query && value.length) { onChange(value.slice(0, -1)); }
  }

  return <div className={styles.picker}>
    <span>{label}</span>
    <div className={styles.field} onClick={event => event.currentTarget.querySelector("input")?.focus()}>
      <Search />
      {value.map(track => (
        <span key={track.id} className={styles.chip}>
          <b>{track.title}</b>{track.artist && <small>{track.artist}</small>}
          <button type="button" onClick={() => onChange(value.filter(item => item.id !== track.id))} aria-label={`Remove ${track.title}`}><X /></button>
        </span>
      ))}
      <input
        value={query}
        onChange={event => { setQuery(event.target.value); }}
        onKeyDown={onKeyDown}
        placeholder={value.length ? "" : "Search tracks"}
        aria-label={label}
      />
    </div>
    {results.length > 0 && <div className={styles.results}>{results.map(track => <button type="button" key={track.id} onClick={() => add(track)}><strong>{track.title}</strong><small>{track.artist || "Unknown artist"} · {track.album || "Unknown album"}</small></button>)}</div>}
  </div>;
}
