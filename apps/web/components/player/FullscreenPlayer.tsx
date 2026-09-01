"use client";

import { AArrowDown, AArrowUp, Disc3, ListMusic, MicVocal, Pause, Play, SkipBack, SkipForward, Type, Volume2, VolumeX, X } from "lucide-react";
import { sizedPlayerCoverArtUrl } from "../media/coverArt";
import LoadingImage from "../media/LoadingImage";
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { trackTemplate } from "../shell/gridGeometry";
import { audioQualityLabel } from "./audioQuality";
import { usePlayer } from "./PlayerProvider";
import styles from "./FullscreenPlayer.module.css";

const stamp = (seconds: number) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;

function FullscreenMarquee({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [distance, setDistance] = useState(0);

  useEffect(() => {
    const el = ref.current;
    const parent = el?.parentElement;
    const inner = el?.firstElementChild;
    if (!el || !parent || !(inner instanceof HTMLElement)) return;
    const update = () => setDistance(Math.max(0, Math.ceil(inner.offsetWidth - parent.clientWidth)));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(parent);
    observer.observe(inner);
    if (document.fonts?.ready) document.fonts.ready.then(update).catch(() => {});
    return () => observer.disconnect();
  }, [children]);

  return <span ref={ref} className={styles.fullscreenMarquee} data-overflowing={distance > 1 || undefined} style={{ "--fullscreen-marquee-offset": `-${distance}px` } as CSSProperties}><span>{children}</span></span>;
}
const isRtlText = (text: string) => {
  for (const character of text) {
    if (/[\u0590-\u08ff]/u.test(character)) return true;
    if (/\p{L}/u.test(character)) return false;
  }
  return false;
};
type LyricsLine = { start_ms: number | null; end_ms?: number; text: string; syllables?: { start_ms: number; end_ms: number; text: string }[] };
type LyricsTextSize = "small" | "normal" | "large";
const lyricsSizeStorageKey = "echora:lyrics-text-size";
const lyricsSizeClasses: Record<LyricsTextSize, string> = {
  small: styles.lyricsSmall,
  normal: styles.lyricsNormal,
  large: styles.lyricsLarge,
};

export default function FullscreenPlayer() {
  const player = usePlayer();
  const [karaokeMode, setKaraokeMode] = useState(true);
  const [lyricsTextSize, setLyricsTextSize] = useState<LyricsTextSize>("normal");
  const [playbackTime, setPlaybackTime] = useState(player.currentTime);
  const [closing, setClosing] = useState(false);
  const [viewport, setViewport] = useState({ width: 1440, height: 900 });
  const [playbackContentHeight, setPlaybackContentHeight] = useState(260);
  const detailsContent = useRef<HTMLDivElement>(null);
  useEffect(() => { document.body.classList.add("echora-fullscreen-player"); return () => { document.body.classList.remove("echora-fullscreen-player"); document.body.classList.remove("echora-fullscreen-player-closing"); }; }, []);
  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      const stored = localStorage.getItem(lyricsSizeStorageKey);
      if (stored === "small" || stored === "normal" || stored === "large") setLyricsTextSize(stored);
    });
    return () => cancelAnimationFrame(frame);
  }, []);
  useEffect(() => {
    const update = (event: Event) => setPlaybackTime((event as CustomEvent<number>).detail);
    window.addEventListener("echora:playback-time", update);
    return () => window.removeEventListener("echora:playback-time", update);
  }, []);
  useEffect(() => {
    const update = () => setViewport({ width: window.innerWidth, height: window.innerHeight });
    const frame = requestAnimationFrame(update);
    window.addEventListener("resize", update);
    return () => { cancelAnimationFrame(frame); window.removeEventListener("resize", update); };
  }, []);
  useEffect(() => {
    const element = detailsContent.current;
    if (!element) return;
    const update = () => setPlaybackContentHeight(Math.ceil(element.getBoundingClientRect().height));
    const observer = new ResizeObserver(update);
    observer.observe(element); const frame = requestAnimationFrame(update);
    return () => { cancelAnimationFrame(frame); observer.disconnect(); };
  }, [player.track]);
  const currentLyrics = player.lyrics?.trackId === player.track?.id ? player.lyrics : null;
  const karaokeAvailable = Boolean(currentLyrics?.karaoke && currentLyrics.lines?.length);
  const karaokeLines = currentLyrics?.lines || [];
  const timedLines = ((karaokeMode && karaokeAvailable ? karaokeLines : currentLyrics?.provenance?.lines) || []).filter(line => Number.isFinite(line.start_ms));
  const activeLine = timedLines.reduce((active, line, index) => Number(line.start_ms) <= playbackTime * 1000 ? index : active, -1);
  if (!player.track) return null;
  const progress = player.duration ? Math.min(100, player.currentTime / player.duration * 100) : 0;
  const headerCover = player.track.coverUrl ? sizedPlayerCoverArtUrl(player.track.coverUrl, 128) : "";
  const mobileCover = player.track.coverUrl ? sizedPlayerCoverArtUrl(player.track.coverUrl, 600) : "";
  const fullCover = player.track.coverUrl ? sizedPlayerCoverArtUrl(player.track.coverUrl, 1200) : "";
  const innerWidth = Math.max(1, viewport.width - 360);
  const innerHeight = Math.max(1, viewport.height - 304);
  const playbackHeight = Math.min(innerHeight * .55, Math.max(160, playbackContentHeight));
  const playbackWeight = playbackHeight / innerHeight;
  const rows = [1 - playbackWeight, playbackWeight];
  const artworkWeight = playbackHeight / innerWidth;
  const spacerWeight = Math.min(.08, Math.max(.045, 72 / innerWidth), (1 - artworkWeight) * .2);
  const columns = [artworkWeight, spacerWeight, 1 - artworkWeight - spacerWeight];
  const mobileLyricsLayout = timedLines.length > 0 || player.lyricsLoading;
  function karaokeLine(line: LyricsLine, active: boolean) {
    if (!active || !karaokeMode || !currentLyrics?.karaoke || !line.syllables?.length) return line.text || "...";
    const now = playbackTime * 1000;
    return <span className={styles.syllables} dir={isRtlText(line.text) ? "rtl" : "ltr"}>{line.syllables.map((syllable, index) => {
      const state = now >= syllable.end_ms ? styles.syllablePast : now >= syllable.start_ms ? styles.syllableActive : styles.syllableNext;
      return <span key={`${syllable.start_ms}-${index}`} className={state}>{syllable.text}</span>;
    })}</span>;
  }
  function chooseLyricsTextSize(size: LyricsTextSize) { localStorage.setItem(lyricsSizeStorageKey, size); setLyricsTextSize(size); }
  function close() { if (closing) return; document.body.classList.add("echora-fullscreen-player-closing"); setClosing(true); window.setTimeout(() => player.setExpanded(false), 520); }
  return <main className={`${styles.player} ${mobileLyricsLayout ? styles.hasMobileLyrics : ""} ${closing ? styles.closing : ""}`}   role="dialog" aria-modal="true" aria-label="Now playing">
    <div className={styles.vignette} />
    <section className={styles.unsupported}><strong>THIS VIEW NEEDS MORE ROOM</strong><p>Resize the window to at least 900 pixels wide or open Echora on a larger screen.</p></section>
    <button className={styles.close} onClick={close} aria-label="Close full screen player"><X /></button>
    {timedLines.length > 0 && <div className={styles.sizeToggle} role="group" aria-label="Lyrics text size">{(["small", "normal", "large"] as LyricsTextSize[]).map(size => { const Icon = size === "small" ? AArrowDown : size === "large" ? AArrowUp : Type; return <button type="button" className={lyricsTextSize === size ? styles.selectedSize : ""} onClick={() => chooseLyricsTextSize(size)} aria-pressed={lyricsTextSize === size} key={size}><Icon />{size.toUpperCase()}</button>; })}</div>}
    {karaokeAvailable && <div className={styles.modeToggle} role="group" aria-label="Lyrics timing mode"><button className={karaokeMode ? styles.selectedMode : ""} onClick={() => setKaraokeMode(true)} aria-pressed={karaokeMode}><MicVocal />KARAOKE</button><button className={!karaokeMode ? styles.selectedMode : ""} onClick={() => setKaraokeMode(false)} aria-pressed={!karaokeMode}><ListMusic />SYNCED</button></div>}
    <section className={styles.mobilePlayer} aria-label="Mobile now playing">
      <header className={styles.mobileTrack}><div className={styles.mobileHeaderArt}>{headerCover ? <LoadingImage sizes="128px" src={headerCover} alt="" priority /> : <Disc3 />}</div><div><span>NOW PLAYING</span><h1><FullscreenMarquee>{player.track.title}</FullscreenMarquee></h1><strong>{player.track.artist || "Unknown artist"}</strong><p><FullscreenMarquee>{player.track.album || "Unknown album"}</FullscreenMarquee></p></div></header>
      <section className={styles.mobileStage}>
        {timedLines.length ? <div className={styles.mobileLyricsStage}> 
          {karaokeAvailable && <div className={styles.mobileLyricsMode} role="group" aria-label="Lyrics timing mode"><button className={karaokeMode ? styles.selectedMobileView : ""} onClick={() => setKaraokeMode(true)} aria-label="Karaoke timing"><MicVocal /></button><button className={!karaokeMode ? styles.selectedMobileView : ""} onClick={() => setKaraokeMode(false)} aria-label="Synced lyrics"><ListMusic /></button></div>}
          <div className={`${styles.mobileLyricsLines} ${lyricsSizeClasses[lyricsTextSize]}`}>{(() => { const index = activeLine >= 0 ? activeLine : 0, line = timedLines[index]; return line ? <button dir={isRtlText(line.text) ? "rtl" : "ltr"} className={styles.activeLine} onClick={() => player.seek(Number(line.start_ms) / 1000)}>{karaokeLine(line, true)}</button> : null; })()}</div>
        </div> : player.lyricsLoading ? <div className={styles.mobileLyricsPlaceholder} /> : <div className={styles.mobileArtwork}>{mobileCover ? <LoadingImage sizes="600px" src={mobileCover} alt="" priority /> : <Disc3 />}</div>}
      </section>
      <section className={styles.mobileDock}><div className={styles.mobileTimeline}><input aria-label="Seek" type="range" min="0" max={player.duration || 0} step="0.1" value={Math.min(player.currentTime, player.duration || 0)} onChange={event => player.seek(Number(event.target.value))} style={{ "--progress": `${progress}%` } as React.CSSProperties} /><div><time>{stamp(player.currentTime)}</time><time>{stamp(player.duration)}</time></div></div><div className={styles.mobileControls}><button onClick={player.previous} aria-label="Previous track"><SkipBack /></button><button className={styles.mobilePlay} onClick={player.toggle} aria-label={player.playing ? "Pause" : "Play"}>{player.playing ? <Pause /> : <Play />}</button><button onClick={player.next} disabled={player.queueIndex >= player.queue.length - 1} aria-label="Next track"><SkipForward /></button><button onClick={player.toggleMute} aria-label={player.muted ? "Unmute" : "Mute"}>{player.muted ? <VolumeX /> : <Volume2 />}</button></div></section>
    </section>
    <section className={styles.grid} style={{ gridTemplateColumns: trackTemplate(columns, 180), gridTemplateRows: trackTemplate(rows, 152) }}> 
      <section className={styles.playbackPanel}>
        <div className={styles.art}>{fullCover ? <LoadingImage sizes="520px" src={fullCover} alt="" priority /> : <Disc3 />}</div>
        <div className={styles.details}><div className={styles.detailsContent} ref={detailsContent}><div className={styles.trackIdentity}><span>NOW PLAYING</span><h1><FullscreenMarquee>{player.track.title}</FullscreenMarquee></h1><strong>{player.track.artist || "Unknown artist"}</strong><p className={styles.metadata}><FullscreenMarquee>{player.track.album || "Unknown album"}</FullscreenMarquee><span>{audioQualityLabel(player.audioQuality)}</span></p></div>
          <div className={styles.timeline}><input aria-label="Seek" type="range" min="0" max={player.duration || 0} step="0.1" value={Math.min(player.currentTime, player.duration || 0)} onChange={event => player.seek(Number(event.target.value))} style={{ "--progress": `${progress}%` } as React.CSSProperties} /><div><time>{stamp(player.currentTime)}</time><time>{stamp(player.duration)}</time></div></div>
          <div className={styles.controls}><button onClick={player.previous}><SkipBack /></button><button className={styles.play} onClick={player.toggle}>{player.playing ? <Pause /> : <Play />}</button><button onClick={player.next} disabled={player.queueIndex >= player.queue.length - 1}><SkipForward /></button><button onClick={player.toggleMute}>{player.muted ? <VolumeX /> : <Volume2 />}</button></div>
        </div></div>
      </section>
      {timedLines.length > 0 && <aside className={`${styles.lyrics} ${styles.mobileLyricsVisible} ${lyricsSizeClasses[lyricsTextSize]}`} key={`${activeLine}-${karaokeMode}`}>
        {[-1, 0, 1].map(offset => { const index = activeLine + offset, line = timedLines[index]; return line ? <button dir={isRtlText(line.text) ? "rtl" : "ltr"} className={offset === 0 ? styles.activeLine : offset < 0 ? styles.pastLine : styles.nextLine} key={`${line.start_ms}-${index}`} onClick={() => player.seek(Number(line.start_ms) / 1000)}>{karaokeLine(line, offset === 0)}</button> : null; })}
      </aside>}
    </section>
  </main>;
}
