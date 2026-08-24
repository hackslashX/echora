"use client";

import { Search, X } from "lucide-react";
import { useEffect, useState } from "react";
import styles from "./TrackReferencePicker.module.css";

export type ReferenceTrack = { id: string; title: string; artist?: string; album?: string };

export default function TrackReferencePicker({ label, value, onChange }: {
  label: string;
  value: ReferenceTrack[];
  onChange: (tracks: ReferenceTrack[]) => void;
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
    onChange([...value, track]);
    setQuery("");
    setResults([]);
  }

  return <div className={styles.picker}>
    <span>{label}</span>
    <label><Search /><input value={query} onChange={event => { const next = event.target.value; setQuery(next); if (next.trim().length < 2) setResults([]); }} placeholder="Search tracks" /></label>
    {results.length > 0 && <div className={styles.results}>{results.map(track => <button type="button" key={track.id} onClick={() => add(track)}><strong>{track.title}</strong><small>{track.artist || "Unknown artist"} · {track.album || "Unknown album"}</small></button>)}</div>}
    {value.length > 0 && <div className={styles.selected}>{value.map(track => <span key={track.id}><b>{track.title}</b><button type="button" onClick={() => onChange(value.filter(item => item.id !== track.id))} aria-label={`Remove ${track.title}`}><X /></button></span>)}</div>}
  </div>;
}
