"use client";

import { AArrowDown, AArrowUp, Disc3, ListMusic, MicVocal, Pause, Play, SkipBack, SkipForward, Type, Volume2, VolumeX, X } from "lucide-react";
import { sizedPlayerCoverArtUrl } from "../media/coverArt";
import LoadingImage from "../media/LoadingImage";
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { trackTemplate } from "../shell/gridGeometry";
import { audioQualityLabel } from "./audioQuality";
import { usePlayer } from "./PlayerProvider";
import styles from "./FullscreenPlayer.module.css";
import motionStyles from "./FullscreenMotion.module.css";
import WaveformSeek from "./WaveformSeek";
import LyricsGlow from "./LyricsGlow";
import AiLyricsNotice from "./AiLyricsNotice";
import { defaultPlaybackPreferences, readPlaybackPreferences, type PlaybackPreferences } from "./playbackPreferences";
import { useDialogFocus } from "../shell/useDialogFocus";

const DESKTOP_INSET = 80;
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
type KaraokeSyllable = NonNullable<LyricsLine["syllables"]>[number];
type LyricsTextSize = "small" | "normal" | "large";
const lyricsSizeStorageKey = "echora:lyrics-text-size";
const lyricsSizeClasses: Record<LyricsTextSize, string> = {
  small: styles.lyricsSmall,
  normal: styles.lyricsNormal,
  large: styles.lyricsLarge,
};

function groupSyllablesByWord(syllables: KaraokeSyllable[]) {
  const words: { syllable: KaraokeSyllable; index: number; text: string; fragmentIndex: number }[][] = [];
  let word: { syllable: KaraokeSyllable; index: number; text: string; fragmentIndex: number }[] = [];
  syllables.forEach((syllable, index) => {
    syllable.text.split(/(\s+)/u).filter(Boolean).forEach((text, fragmentIndex) => {
      word.push({ syllable, index, text, fragmentIndex });
      if (/^\s+$/u.test(text)) {
        words.push(word);
        word = [];
      }
    });
  });
  if (word.length) words.push(word);
  return words;
}

export default function FullscreenPlayer() {
  const player = usePlayer();
  const dialogRef = useRef<HTMLElement>(null);
  useDialogFocus(dialogRef, Boolean(player.track), () => close());
  const [karaokeMode, setKaraokeMode] = useState(true);
  const [highlightStyle, setHighlightStyle] = useState(defaultPlaybackPreferences.karaokeHighlightStyle);
  useEffect(() => {
    const accept = (value: PlaybackPreferences) => setHighlightStyle(value.karaokeHighlightStyle === "syllable" ? "syllable" : "lava");
    const frame = requestAnimationFrame(() => accept(readPlaybackPreferences()));
    const update = (event: Event) => accept((event as CustomEvent<PlaybackPreferences>).detail);
    window.addEventListener("echora:playback-preferences", update);
    return () => { cancelAnimationFrame(frame); window.removeEventListener("echora:playback-preferences", update); };
  }, []);
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
  const aiLyrics = currentLyrics?.provenance?.ai_generated === true;
  const karaokeAvailable = Boolean(currentLyrics?.karaoke && currentLyrics.lines?.length);
  const karaokeLines = currentLyrics?.lines || [];
  const timedLines = ((karaokeMode && karaokeAvailable ? karaokeLines : currentLyrics?.provenance?.lines) || []).filter(line => Number.isFinite(line.start_ms));
  const activeLine = timedLines.reduce((active, line, index) => Number(line.start_ms) <= playbackTime * 1000 ? index : active, -1);
  if (!player.track) return null;
  const mobileCover = player.track.coverUrl ? sizedPlayerCoverArtUrl(player.track.coverUrl, 800) : "";
  const fullCover = player.track.coverUrl ? sizedPlayerCoverArtUrl(player.track.coverUrl, 1200) : "";
  const innerWidth = Math.max(1, viewport.width - DESKTOP_INSET * 2);
  const innerHeight = Math.max(1, viewport.height - DESKTOP_INSET * 2);
  const playbackHeight = Math.min(innerHeight * .46, Math.max(148, playbackContentHeight));
  const playbackWeight = playbackHeight / innerHeight;
  const rows = [1 - playbackWeight, playbackWeight];
  const artworkWeight = playbackHeight / innerWidth;
  const spacerWeight = Math.min(.08, Math.max(.045, 72 / innerWidth), (1 - artworkWeight) * .2);
  const playbackWidth = Math.min(.9, Math.max(.64, artworkWeight + spacerWeight + .2));
  const columns = [artworkWeight, spacerWeight, playbackWidth - artworkWeight - spacerWeight, 1 - playbackWidth];
  const mobileLyricsLayout = timedLines.length > 0 || player.lyricsLoading;
  function karaokeLine(line: LyricsLine, active: boolean) {
    if (!karaokeMode || !currentLyrics?.karaoke || !line.syllables?.length) return line.text || "...";
    const now = playbackTime * 1000;
    const rtl = isRtlText(line.text);
    return <span className={styles.syllables} dir={rtl ? "rtl" : "ltr"}>{groupSyllablesByWord(line.syllables).map((word, wordIndex) => <span key={wordIndex} style={{ display: "inline-block", whiteSpace: "pre" }}>{word.map(({ syllable, index, text, fragmentIndex }) => {
      // CSS masks on an inline whitespace box can paint as a solid rectangle
      // while the fullscreen layer is composited. Spaces need no timing paint.
      if (/^\s+$/u.test(text)) return text;
      const singing = active && now >= syllable.start_ms && now < syllable.end_ms;
      const state = now >= syllable.end_ms ? styles.syllablePast : singing ? styles.syllableActive : styles.syllableNext;
      if (highlightStyle === "syllable") return <span key={`${syllable.start_ms}-${index}-${fragmentIndex}`} className={state}
        style={{ position: "relative", display: "inline-block", color: "transparent", WebkitBackgroundClip: "text", backgroundClip: "text" }} data-lyric-singing={singing ? "true" : undefined}>{text}</span>;
      const progress = Math.min(100, Math.max(0, (now - syllable.start_ms) / Math.max(1, syllable.end_ms - syllable.start_ms) * 100));
      // A curved mask clips a second copy of the glyph, rather than layering
      // decorative bubbles over a straight gradient boundary.
      const edge = rtl ? 100 - progress : progress;
      const amplitude = Math.min(6, progress * .6, (100 - progress) * .6);
      const phase = now / 320 + index * .8;
      const boundary = Array.from({ length: 21 }, (_, point) => {
        const y = point * 5;
        const x = edge + Math.sin(y / 100 * Math.PI * 2 + phase) * amplitude;
        return `L${x.toFixed(2)},${y}`;
      }).join(" ");
      const side = rtl ? 100 : 0;
      const mask = `url("data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" preserveAspectRatio="none"><path fill="white" d="M${side},0 ${boundary} L${side},100 Z"/></svg>`)}")`;
      const liquid: CSSProperties = {
        position: "absolute", inset: 0, color: "var(--aqua)",
        maskImage: mask, WebkitMaskImage: mask,
        maskSize: "100% 100%", WebkitMaskSize: "100% 100%",
        maskRepeat: "no-repeat", WebkitMaskRepeat: "no-repeat",
        pointerEvents: "none",
      };
      return <span key={`${syllable.start_ms}-${index}-${fragmentIndex}`} className={state}
        style={{ position: "relative", display: "inline-block", color: "transparent", WebkitBackgroundClip: "text", backgroundClip: "text", ...(singing ? { background: "none", color: "#fff", textShadow: "none" } : {}) }}
        data-lyric-singing={singing ? "true" : undefined}>{text}
        {singing && <span aria-hidden="true" style={liquid}>{text}</span>}
      </span>;
    })}</span>)}</span>;
  }
  function chooseLyricsTextSize(size: LyricsTextSize) { localStorage.setItem(lyricsSizeStorageKey, size); setLyricsTextSize(size); }
  function close() { if (closing) return; document.body.classList.add("echora-fullscreen-player-closing"); setClosing(true); const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches; window.setTimeout(() => player.setExpanded(false), reduced ? 0 : 280); }
  return <main ref={dialogRef} tabIndex={-1} className={`${styles.player} ${motionStyles.surface} ${mobileLyricsLayout ? styles.hasMobileLyrics : ""} ${closing ? `${styles.closing} ${motionStyles.closing}` : ""}`} role="dialog" aria-modal="true" aria-label="Now playing">
    <div className={styles.vignette} />
    <LyricsGlow container={dialogRef} playing={player.playing} />
    <section className={styles.unsupported}><strong>THIS VIEW NEEDS MORE ROOM</strong><p>Resize the window to at least 900 pixels wide or open Echora on a larger screen.</p></section>
    <button className={`${styles.close} ${motionStyles.content}`} onClick={close} aria-label="Close full screen player"><X /></button>
    {timedLines.length > 0 && <div className={styles.sizeToggle} role="group" aria-label="Lyrics text size">{(["small", "normal", "large"] as LyricsTextSize[]).map(size => { const Icon = size === "small" ? AArrowDown : size === "large" ? AArrowUp : Type; return <button type="button" className={lyricsTextSize === size ? styles.selectedSize : ""} onClick={() => chooseLyricsTextSize(size)} aria-pressed={lyricsTextSize === size} key={size}><Icon />{size.toUpperCase()}</button>; })}</div>}
    {karaokeAvailable && <div className={styles.modeToggle} role="group" aria-label="Lyrics timing mode"><button className={karaokeMode ? styles.selectedMode : ""} onClick={() => setKaraokeMode(true)} aria-pressed={karaokeMode}><MicVocal />KARAOKE</button><button className={!karaokeMode ? styles.selectedMode : ""} onClick={() => setKaraokeMode(false)} aria-pressed={!karaokeMode}><ListMusic />SYNCED</button></div>}
    <section className={`${styles.mobilePlayer} ${motionStyles.content}`} aria-label="Mobile now playing">
      <header className={styles.mobileTrack}><div className={styles.mobileHeaderArt}>{mobileCover ? <LoadingImage sizes="260px" src={mobileCover} alt="" priority /> : <Disc3 />}</div><div><span>NOW PLAYING</span><h1><FullscreenMarquee>{player.track.title}</FullscreenMarquee></h1><strong>{player.track.artist || "Unknown artist"}</strong><p><FullscreenMarquee>{player.track.album || "Unknown album"}</FullscreenMarquee></p></div></header>
      <section className={styles.mobileStage}>
        {timedLines.length ? <div className={`${styles.mobileLyricsStage} ${aiLyrics ? styles.withAiNotice : ""}`}>
          {karaokeAvailable && <div className={styles.mobileLyricsMode} role="group" aria-label="Lyrics timing mode"><button className={karaokeMode ? styles.selectedMobileView : ""} onClick={() => setKaraokeMode(true)} aria-label="Karaoke timing"><MicVocal /></button><button className={!karaokeMode ? styles.selectedMobileView : ""} onClick={() => setKaraokeMode(false)} aria-label="Synced lyrics"><ListMusic /></button></div>}
          <div className={`${styles.mobileLyricsLines} ${lyricsSizeClasses[lyricsTextSize]}`}>{(() => { const index = activeLine >= 0 ? activeLine : 0, line = timedLines[index]; return line ? <button dir={isRtlText(line.text) ? "rtl" : "ltr"} className={styles.activeLine} style={{ paddingBottom: ".14em", overflow: "visible" }} data-lyric-singing={!karaokeMode && activeLine >= 0 ? "true" : undefined} onClick={() => player.seek(Number(line.start_ms) / 1000)}>{karaokeLine(line, true)}</button> : null; })()}</div>
          {aiLyrics && <div className={styles.mobileAiNotice}><AiLyricsNotice /></div>}
        </div> : player.lyricsLoading ? <div className={styles.mobileLyricsPlaceholder} /> : <div className={styles.mobileArtwork}>{mobileCover ? <LoadingImage sizes="min(100vw, 340px)" src={mobileCover} alt="" priority /> : <Disc3 />}</div>}
      </section>
      <section className={styles.mobileDock}><div className={styles.mobileTimeline}><WaveformSeek /><div><time>{stamp(player.currentTime)}</time><time>{stamp(player.duration)}</time></div></div><div className={styles.mobileControls}><button onClick={player.previous} aria-label="Previous track"><SkipBack /></button><button className={styles.mobilePlay} onClick={player.toggle} aria-label={player.playing ? "Pause" : "Play"}>{player.playing ? <Pause /> : <Play />}</button><button onClick={player.next} disabled={player.queueIndex >= player.queue.length - 1} aria-label="Next track"><SkipForward /></button><button onClick={player.toggleMute} aria-label={player.muted ? "Unmute" : "Mute"}>{player.muted ? <VolumeX /> : <Volume2 />}</button></div></section>
    </section>
    <section className={`${styles.grid} ${motionStyles.content}`} style={{ gridTemplateColumns: trackTemplate(columns, DESKTOP_INSET), gridTemplateRows: trackTemplate(rows, DESKTOP_INSET) }}>
      <section className={styles.playbackPanel}>
        <div className={styles.art}>{fullCover ? <LoadingImage sizes="520px" src={fullCover} alt="" priority /> : <Disc3 />}</div>
        <div className={styles.details}><div className={styles.detailsContent} ref={detailsContent}><div className={styles.trackIdentity}><span>NOW PLAYING</span><h1><FullscreenMarquee>{player.track.title}</FullscreenMarquee></h1><strong>{player.track.artist || "Unknown artist"}</strong><p className={styles.metadata}>{player.track.album || "Unknown album"}<span>{audioQualityLabel(player.audioQuality)}</span></p></div>
          <div className={styles.timeline}><WaveformSeek /><div><time>{stamp(player.currentTime)}</time><time>{stamp(player.duration)}</time></div></div>
          <div className={styles.controls}><button aria-label="Previous track" onClick={player.previous}><SkipBack /></button><button aria-label={player.playing ? "Pause" : "Play"} className={styles.play} onClick={player.toggle}>{player.playing ? <Pause /> : <Play />}</button><button aria-label="Next track" onClick={player.next} disabled={player.queueIndex >= player.queue.length - 1}><SkipForward /></button><button aria-label={player.muted ? "Unmute" : "Mute"} onClick={player.toggleMute}>{player.muted ? <VolumeX /> : <Volume2 />}</button></div>
        </div></div>
      </section>
      {timedLines.length > 0 && <aside className={`${styles.lyrics} ${styles.mobileLyricsVisible} ${lyricsSizeClasses[lyricsTextSize]}`} key={`${activeLine}-${karaokeMode}`}>
        {[-1, 0, 1].map(offset => { const index = activeLine + offset, line = timedLines[index]; return line ? <button dir={isRtlText(line.text) ? "rtl" : "ltr"} className={offset === 0 ? styles.activeLine : offset < 0 ? styles.pastLine : styles.nextLine} key={`${line.start_ms}-${index}`} data-lyric-singing={offset === 0 && !karaokeMode ? "true" : undefined} onClick={() => player.seek(Number(line.start_ms) / 1000)}>{karaokeLine(line, offset === 0)}</button> : null; })}
      </aside>}
      {aiLyrics && timedLines.length > 0 && <div className={styles.desktopAiNotice}><AiLyricsNotice /></div>}
    </section>
  </main>;
}
