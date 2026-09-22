"use client";

import { Disc3, Search } from "lucide-react";
import { coverArtUrl } from "../media/coverArt"
import { mediaUrl } from "../media/mediaOrigin";
import LoadingImage from "../media/LoadingImage";
import { useEffect, useRef, useState } from "react";
import { usePlayer } from "../player/PlayerProvider";
import AppShell from "../shell/AppShell";
import CopyrightFooter from "../shell/CopyrightFooter";
import { trackTemplate } from "../shell/gridGeometry";
import MobilePivots from "../shell/MobilePivots";
import { useMobilePane } from "../shell/useMobilePane";
import CardHeader from "../ui/CardHeader";
import HumSearchButton from "./HumSearchButton";
import RecordingSearchButton from "./RecordingSearchButton";
import RecordingMatchNotice from "./RecordingMatchNotice";
import { canCurateRecording, curationHref, resultConnection, recordingQualityLabel, type RecordingQuality } from "./recordingSearch";
import TransitionLink from "../shell/TransitionLink";
import TrackMenu from "./TrackMenu";
import styles from "./BrowseLibrary.module.css";

type Track = { connection_id?: string; id: string; title: string; artist?: string; album?: string; duration_seconds: number; source_id?: string; cover_art?: string; similarity?: number; matched_at_seconds?: number; matched_source?: string; lyrics_status?: string; recording_score?: number; recording_confirmed?: boolean; recording_quality?: RecordingQuality };
type Facet = { name: string; tracks: number };
const duration = (seconds: number) => {
  const rounded = Math.max(0, Math.round(seconds));
  return `${Math.floor(rounded / 60)}:${String(rounded % 60).padStart(2, "0")}`;
};

export default function BrowseLibrary() {
  const player = usePlayer();
  const recordingRef = useRef<{ cancel: () => void }>(null);
  const humRef = useRef<{ cancel: () => void }>(null);
  function invalidateSearches() { recordingRef.current?.cancel(); humRef.current?.cancel(); }
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
  const [selectedConnectionId, setConnectionId] = useState("");
  const [recordingWarning, setRecordingWarning] = useState("");
  const [searchMode, setSearchMode] = useState<"hum" | "recording" | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [mobilePane, setMobilePane, paneTransition] = useMobilePane<"tracks" | "filters">("tracks", ["tracks", "filters"]);
  const listRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const pageSize = 10;

  useEffect(() => {
    fetch("/analysis/auth/me").then(response => response.ok ? response.json() : null).then(user => setConnectionId(user?.navidrome_connection_id || "")).catch(() => {});
  }, []);

  useEffect(() => {
    if (searchMode) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true); setError("");
      const params = new URLSearchParams({ limit: String(pageSize), offset: String(batch * pageSize), q: query, artist, album, sort_by: sortBy });
      fetch(`/analysis/library/tracks?${params}`, { signal: controller.signal }).then(async response => {
        const body = await response.json(); if (!response.ok) throw new Error(body.detail || "Could not load tracks");
        if (controller.signal.aborted) return;
        setTracks(current => batch === 0 ? body.tracks : [...current, ...body.tracks.filter((track: Track) => !current.some(item => item.id === track.id))]);
        setTotal(body.total);
      }).catch(reason => { if (reason.name !== "AbortError") setError(reason instanceof Error ? reason.message : "Could not load tracks"); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, batch === 0 ? 220 : 0);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [album, artist, batch, searchMode, query, refreshToken, sortBy]);

  useEffect(() => {
    const root = listRef.current, sentinel = sentinelRef.current;
    if (!root || !sentinel || searchMode || loading || tracks.length >= total) return;
    const observer = new IntersectionObserver(entries => { if (entries[0]?.isIntersecting) setBatch(value => value + 1); }, { root, rootMargin: "180px 0px" });
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [searchMode, loading, total, tracks.length]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const params = new URLSearchParams({ artist_query: artistQuery, album_query: albumQuery, artist, limit: "20" });
      fetch(`/analysis/library/facets?${params}`).then(response => response.ok ? response.json() : null).then(body => { if (body) { setArtists(body.artists); setAlbums(body.albums); } }).catch(() => {});
    }, 180);
    return () => window.clearTimeout(timer);
  }, [albumQuery, artist, artistQuery]);

  function resetResults() { invalidateSearches(); setError(""); setRecordingWarning(""); setSearchMode(null); setTracks([]); setTotal(0); setBatch(0); listRef.current?.scrollTo({ top: 0 }); }

  function showHumResults(results: Track[]) {
    setRecordingWarning(""); setSearchMode("hum"); setLoading(false); setTracks(results); setTotal(results.length); setBatch(0); setMobilePane("tracks");
    listRef.current?.scrollTo({ top: 0 });
  }

  function showRecordingResults(results: Track[], warning: string) {
    setRecordingWarning(warning); setSearchMode("recording"); setLoading(false); setTracks(results); setTotal(results.length); setBatch(0); setMobilePane("tracks");
    listRef.current?.scrollTo({ top: 0 });
  }

  function playerTrack(track: Track) {
    const connectionId = resultConnection(track, selectedConnectionId);
    if (!connectionId || !track.source_id) return null;
    return {
      id: track.id, title: track.title, artist: track.artist, album: track.album, durationSeconds: track.duration_seconds,
      streamUrl: mediaUrl(`/navidrome/connections/${connectionId}/stream/${encodeURIComponent(track.source_id)}`),
      connectionId, sourceId: track.source_id,
      coverUrl: track.cover_art ? coverArtUrl(connectionId, track.cover_art) : undefined,
    };
  }
  function play(track: Track) { const next = playerTrack(track); if (next) player.play(next); }

  const columns = [0.27, 0.04, 0.69];
  const rows = [1];
  return <AppShell title="Browse" footer={<CopyrightFooter />} grid={{ columns, rows }} flush fullPage breadcrumb>
    <section className={styles.layout} style={{ gridTemplateColumns: trackTemplate(columns, 160), gridTemplateRows: trackTemplate(rows, 88) }}>
      <MobilePivots label="Browse sections" active={mobilePane} onChange={setMobilePane} items={[{ key: "tracks", label: searchMode ? "matches" : "tracks", count: total }, { key: "filters", label: "filters" }]} />
      <aside className={`${styles.filters} ${mobilePane === "filters" ? `${styles.mobileActive} ${paneTransition}` : ""}`}>
        <CardHeader as="h1" title="Filters" />
        <section className={styles.filterGroup}><span>Artists</span><input value={artistQuery} onChange={event => { invalidateSearches(); setArtistQuery(event.target.value); }} placeholder="Search artists" /><div><button type="button" className={!artist ? styles.selected : ""} onClick={() => { setArtist(""); setAlbum(""); resetResults(); }}>All artists</button>{artists.map(item => <button type="button" className={artist === item.name ? styles.selected : ""} onClick={() => { setArtist(item.name); setAlbum(""); resetResults(); }} key={item.name}>{item.name}<b>{item.tracks}</b></button>)}</div></section>
        <section className={styles.filterGroup}><span>Albums</span><input value={albumQuery} onChange={event => { invalidateSearches(); setAlbumQuery(event.target.value); }} placeholder="Search albums" /><div><button type="button" className={!album ? styles.selected : ""} onClick={() => { setAlbum(""); resetResults(); }}>All albums</button>{albums.map(item => <button type="button" className={album === item.name ? styles.selected : ""} onClick={() => { setAlbum(item.name); resetResults(); }} key={item.name}>{item.name}<b>{item.tracks}</b></button>)}</div></section>
      </aside>
      <section className={`${styles.listing} ${mobilePane === "tracks" ? `${styles.mobileActive} ${paneTransition}` : ""}`}>
        <CardHeader title={searchMode === "recording" ? "Recording results" : searchMode === "hum" ? "Hum matches" : "Tracks"} count={total} />
        <div className={styles.search}><label><Search /><input value={query} onChange={event => { setQuery(event.target.value); resetResults(); }} placeholder="Search tracks" /></label><HumSearchButton ref={humRef} onStart={invalidateSearches} onResults={showHumResults} onError={setError} /><RecordingSearchButton ref={recordingRef} onResults={showRecordingResults} onError={setError} onStart={invalidateSearches} /><select aria-label="Sort tracks" value={sortBy} onChange={event => { setSortBy(event.target.value as "name" | "artist" | "released"); resetResults(); }}><option value="name">Name</option><option value="artist">Artist</option><option value="released">Date released</option></select></div>
        <div className={styles.list} ref={listRef}>{error && <div className={styles.feedback} role="alert">{error}</div>}{loading && tracks.length === 0 ? <div className={styles.empty}>Loading library</div> : tracks.length === 0 ? <div className={styles.empty}>No matching tracks</div> : <>{searchMode === "recording" && <RecordingMatchNotice message={recordingWarning} />}{tracks.map((track, index) => <article className={`${styles.row} ${player.track?.id === track.id ? styles.current : ""}`} key={track.id}>
          <button type="button" className={styles.playTrack} onClick={() => play(track)} disabled={!playerTrack(track)}>
            <span className={styles.art}>{track.cover_art && resultConnection(track, selectedConnectionId) ? <LoadingImage sizes="48px" alt="" src={coverArtUrl(resultConnection(track, selectedConnectionId), track.cover_art, 96)} /> : <Disc3 />}</span>
            <span className={styles.track}><strong>{track.title}</strong><small>{track.artist || "Unknown artist"}</small>{track.matched_source === "recording" && <span className={styles.recordingMetadata}>{recordingQualityLabel(track.recording_quality ?? "possible")} · Score {track.recording_score?.toFixed(3)}<br />{track.recording_confirmed ? "Match position" : "Possible position"} · {duration(track.matched_at_seconds || 0)}</span>}</span><span className={styles.album}>{track.matched_source === "recording" ? `${track.recording_confirmed ? "Match position" : "Possible position"} · ${duration(track.matched_at_seconds || 0)}` : track.similarity == null ? track.album || "Unknown album" : `${Math.round(track.similarity * 100)}% match · ${duration(track.matched_at_seconds || 0)} · ${track.matched_source || "melody"}`}</span><time>{duration(track.duration_seconds)}</time>
          </button>
          <TrackMenu track={{ ...track, connectionId: resultConnection(track, selectedConnectionId), streamUrl: playerTrack(track)?.streamUrl, coverUrl: playerTrack(track)?.coverUrl }} onSaved={() => { if (searchMode) return; setTracks([]); setTotal(0); setBatch(0); setRefreshToken(value => value + 1); }} />
          {canCurateRecording(track, index) && <nav className={styles.recordingActions} aria-label={`Explore ${track.title}`}><TransitionLink href={curationHref(track.id, "similar")}>More like this</TransitionLink><TransitionLink href={curationHref(track.id, "journey")}>Start journey</TransitionLink></nav>}
        </article>)}<div ref={sentinelRef} className={styles.sentinel}>{loading ? "Loading more tracks" : tracks.length < total ? "Scroll for more" : `${tracks.length} tracks loaded`}</div></>}</div>
      </section>
    </section>
  </AppShell>;
}
