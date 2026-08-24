"use client";

import { Disc3 } from "lucide-react";
import { useEffect, useState } from "react";
import AppShell from "../shell/AppShell";
import CopyrightFooter from "../shell/CopyrightFooter";
import TransitionLink from "../shell/TransitionLink";
import { trackTemplate } from "../shell/gridGeometry";
import styles from "./ArtistProfileView.module.css";

type Track = { id: string; title: string; artist?: string; album?: string };
type Facet = { index: number; weight: number; track_count: number; representative_track: Track };
type Profile = { artist: string; model: string; track_count: number; component_count: number; facets: Facet[] };
type Similar = Profile & { similarity: number; target_coverage: number; candidate_coverage: number; strongest_facet_match: { target_facet: number; candidate_facet: number; similarity: number } };

export default function ArtistProfileView({ artist }: { artist: string }) {
  const [model, setModel] = useState("muq_mulan");
  const [profile, setProfile] = useState<Profile | null>(null);
  const [similar, setSimilar] = useState<Similar[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    const query = new URLSearchParams({ artist, model });
    Promise.all([
      fetch(`/analysis/library/artists/profile?${query}`, { signal: controller.signal }).then(response => response.ok ? response.json() : Promise.reject(new Error("Artist profile unavailable"))),
      fetch(`/analysis/library/artists/similar?${query}`, { signal: controller.signal }).then(response => response.ok ? response.json() : Promise.reject(new Error("Artist similarities unavailable"))),
    ]).then(([nextProfile, nextSimilar]) => { setProfile(nextProfile); setSimilar(nextSimilar.results || []); })
      .catch(reason => { if (reason.name !== "AbortError") setError(reason.message); }).finally(() => setLoading(false));
    return () => controller.abort();
  }, [artist, model]);

  const columns = [0.34, 0.04, 0.62];
  const rows = [1];
  return <AppShell title="Artist profile" footer={<CopyrightFooter />} grid={{ columns, rows }} flush fullPage breadcrumb>
    <main className={styles.layout} style={{ gridTemplateColumns: trackTemplate(columns, 180), gridTemplateRows: trackTemplate(rows, 152) }}>
      <aside className={styles.profile}>
        <header><span>ARTIST REPRESENTATION</span><h1>{artist}</h1><div><button className={model === "muq_mulan" ? styles.active : ""} onClick={() => { setLoading(true); setError(""); setModel("muq_mulan"); }}>SEMANTIC</button><button className={model === "mert" ? styles.active : ""} onClick={() => { setLoading(true); setError(""); setModel("mert"); }}>ACOUSTIC</button></div></header>
        {loading ? <p className={styles.empty}>Building catalogue facets</p> : error ? <p className={styles.empty}>{error}</p> : profile && <><dl><div><dt>TRACKS</dt><dd>{profile.track_count}</dd></div><div><dt>FACETS</dt><dd>{profile.component_count}</dd></div></dl><section className={styles.facets}>{profile.facets.map(facet => <article key={facet.index}><span><Disc3 /></span><div><small>FACET {facet.index + 1} · {Math.round(facet.weight * 100)}% · {facet.track_count} TRACKS</small><strong>{facet.representative_track.title}</strong><p>{facet.representative_track.album || "Unknown album"}</p></div></article>)}</section></>}
      </aside>
      <section className={styles.similar}><header><h2>Similar artists</h2><span>Bidirectional facet matching</span></header><div>{similar.map(item => <TransitionLink href={`/artists/${encodeURIComponent(item.artist)}`} key={item.artist}><span className={styles.score}>{Math.round(item.similarity * 100)}</span><div><strong>{item.artist}</strong><p>{item.track_count} tracks · {item.component_count} facets</p><small>BEST MATCH&nbsp; F{item.strongest_facet_match.target_facet + 1} → F{item.strongest_facet_match.candidate_facet + 1}&nbsp; {Math.round(item.strongest_facet_match.similarity * 100)}%</small></div></TransitionLink>)}</div></section>
    </main>
  </AppShell>;
}
