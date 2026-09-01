"use client";

import { Disc3, Search } from "lucide-react";
import { coverArtUrl } from "../media/coverArt";
import LoadingImage from "../media/LoadingImage";
import { useEffect, useRef, useState } from "react";
import { usePlayer } from "../player/PlayerProvider";
import AppShell from "../shell/AppShell";
import CopyrightFooter from "../shell/CopyrightFooter";
import { trackTemplate } from "../shell/gridGeometry";
import HumSearchButton from "./HumSearchButton";
import styles from "./BrowseLibrary.module.css";

type Track = { id: string; title: string; artist?: string; album?: string; duration_seconds: number; source_id?: string; cover_art?: string; similarity?: number; matched_at_seconds?: number; matched_source?: string };
type Facet = { name: string; tracks: number };
const duration = (seconds: number) => `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, "0")}`;

export default function BrowseLibrary() {
  const player = usePlayer();
  const [tracks, setTracks] = useState<Track[]>([]);
  const [artists, setArtists] = useState<Facet[]>([]);
  const [albums, setAlbums] = useState<Facet[]>([]);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [artist, setArtist] = useState("");
  const [album, setAlbum] = useState("");
  const [artistQuery, setArtistQuery] = useState("");
  const [albumQuery, setAlbumQuery] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [batch, setBatch] = useState(0);
  const [sortBy, setSortBy] = useState<"name" | "artist" | "released">("name");
  const [connectionId, setConnectionId] = useState("");
  const [humResults, setHumResults] = useState(false);
  const [mobilePane, setMobilePane] = useState<"tracks" | "filters">("tracks");
  const listRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const pageSize = 10;

  useEffect(() => {
    fetch("/analysis/auth/me").then(response => response.ok ? response.json() : null).then(user => setConnectionId(user?.navidrome_connection_id || "")).catch(() => {});
  }, []);

  useEffect(() => {
    if (humResults) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true); setError("");
      const params = new URLSearchParams({ limit: String(pageSize), offset: String(batch * pageSize), q: query, artist, album, sort_by: sortBy });
      fetch(`/analysis/library/tracks?${params}`, { signal: controller.signal }).then(async response => {
        const body = await response.json(); if (!response.ok) throw new Error(body.detail || "Could not load tracks");
        setTracks(current => batch === 0 ? body.tracks : [...current, ...body.tracks.filter((track: Track) => !current.some(item => item.id === track.id))]);
        setTotal(body.total);
      }).catch(reason => { if (reason.name !== "AbortError") setError(reason instanceof Error ? reason.message : "Could not load tracks"); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, batch === 0 ? 220 : 0);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [album, artist, batch, humResults, query, sortBy]);

  useEffect(() => {
    const root = listRef.current, sentinel = sentinelRef.current;
    if (!root || !sentinel || humResults || loading || tracks.length >= total) return;
    const observer = new IntersectionObserver(entries => { if (entries[0]?.isIntersecting) setBatch(value => value + 1); }, { root, rootMargin: "180px 0px" });
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [humResults, loading, total, tracks.length]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const params = new URLSearchParams({ artist_query: artistQuery, album_query: albumQuery, artist, limit: "20" });
      fetch(`/analysis/library/facets?${params}`).then(response => response.ok ? response.json() : null).then(body => { if (body) { setArtists(body.artists); setAlbums(body.albums); } }).catch(() => {});
    }, 180);
    return () => window.clearTimeout(timer);
  }, [albumQuery, artist, artistQuery]);

  function resetResults() { setHumResults(false); setTracks([]); setTotal(0); setBatch(0); listRef.current?.scrollTo({ top: 0 }); }

  function showHumResults(results: Track[]) {
    setHumResults(true); setTracks(results); setTotal(results.length); setBatch(0); setMobilePane("tracks");
    listRef.current?.scrollTo({ top: 0 });
  }

  function play(track: Track) {
    if (!connectionId || !track.source_id) return;
    player.play({
      id: track.id, title: track.title, artist: track.artist, album: track.album, durationSeconds: track.duration_seconds,
      streamUrl: `/analysis/navidrome/connections/${connectionId}/stream/${encodeURIComponent(track.source_id)}`,
      coverUrl: track.cover_art ? coverArtUrl(connectionId, track.cover_art) : undefined,
    });
  }

  const columns = [0.27, 0.04, 0.69];
  const rows = [1];
  return <AppShell title="Browse" footer={<CopyrightFooter />} grid={{ columns, rows }} flush fullPage breadcrumb>
    <section className={styles.layout} style={{ gridTemplateColumns: trackTemplate(columns, 180), gridTemplateRows: trackTemplate(rows, 152) }}>
      <nav className={styles.mobilePivots} aria-label="Browse sections"><button className={mobilePane === "tracks" ? styles.activePivot : ""} onClick={() => setMobilePane("tracks")}>tracks <b>{total}</b></button><button className={mobilePane === "filters" ? styles.activePivot : ""} onClick={() => setMobilePane("filters")}>filters</button></nav>
      <aside className={`${styles.filters} ${mobilePane === "filters" ? styles.mobileActive : ""}`}>
        <h1>Filters</h1>
        <section className={styles.filterGroup}><span>Artists</span><input value={artistQuery} onChange={event => setArtistQuery(event.target.value)} placeholder="Search artists" /><div><button type="button" className={!artist ? styles.selected : ""} onClick={() => { setArtist(""); setAlbum(""); resetResults(); }}>All artists</button>{artists.map(item => <button type="button" className={artist === item.name ? styles.selected : ""} onClick={() => { setArtist(item.name); setAlbum(""); resetResults(); }} key={item.name}>{item.name}<b>{item.tracks}</b></button>)}</div></section>
        <section className={styles.filterGroup}><span>Albums</span><input value={albumQuery} onChange={event => setAlbumQuery(event.target.value)} placeholder="Search albums" /><div><button type="button" className={!album ? styles.selected : ""} onClick={() => { setAlbum(""); resetResults(); }}>All albums</button>{albums.map(item => <button type="button" className={album === item.name ? styles.selected : ""} onClick={() => { setAlbum(item.name); resetResults(); }} key={item.name}>{item.name}<b>{item.tracks}</b></button>)}</div></section>
      </aside>
      <section className={`${styles.listing} ${mobilePane === "tracks" ? styles.mobileActive : ""}`}>
        <header><h2>{humResults ? "Hum matches" : "Tracks"}</h2><strong>{total}</strong></header>
        <div className={styles.search}><label><Search /><input value={query} onChange={event => { setQuery(event.target.value); resetResults(); }} placeholder="Search tracks" /></label><HumSearchButton onResults={showHumResults} onError={setError} /><select aria-label="Sort tracks" value={sortBy} onChange={event => { setSortBy(event.target.value as "name" | "artist" | "released"); resetResults(); }}><option value="name">Name</option><option value="artist">Artist</option><option value="released">Date released</option></select></div>
        <div className={styles.list} ref={listRef}>{loading && tracks.length === 0 ? <div className={styles.empty}>Loading library</div> : error ? <div className={styles.empty}>{error}</div> : tracks.length === 0 ? <div className={styles.empty}>No matching tracks</div> : <>{tracks.map(track => <button type="button" className={`${styles.row} ${player.track?.id === track.id ? styles.current : ""}`} key={track.id} onClick={() => play(track)} disabled={!connectionId || !track.source_id}>
          <span className={styles.art}>{track.cover_art && connectionId ? <LoadingImage sizes="48px" alt="" src={coverArtUrl(connectionId, track.cover_art, 96)} /> : <Disc3 />}</span>
          <span className={styles.track}><strong>{track.title}</strong><small>{track.artist || "Unknown artist"}</small></span><span className={styles.album}>{track.similarity == null ? track.album || "Unknown album" : `${Math.round(track.similarity * 100)}% match · ${duration(track.matched_at_seconds || 0)} · ${track.matched_source || "melody"}`}</span><time>{duration(track.duration_seconds)}</time>
        </button>)}<div ref={sentinelRef} className={styles.sentinel}>{loading ? "Loading more tracks" : tracks.length < total ? "Scroll for more" : `${tracks.length} tracks loaded`}</div></>}</div>
      </section>
    </section>
  </AppShell>;
}
