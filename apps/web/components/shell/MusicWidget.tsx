"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Disc3, Pause, Play, SkipBack, SkipForward, Volume2, VolumeX } from "lucide-react";
import { sizedPlayerCoverArtUrl } from "../media/coverArt";
import LoadingImage from "../media/LoadingImage";
import { audioQualityLabel } from "../player/audioQuality";
import { usePlayer } from "../player/PlayerProvider";
import styles from "./MusicWidget.module.css";
import WaveformSeek from "../player/WaveformSeek";

const stamp = (seconds: number) => {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
};

function Marquee({ children, className }: { children: ReactNode; className: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [overflowing, setOverflowing] = useState(false);

  useEffect(() => {
    const el = ref.current;
    const parent = el?.parentElement;
    const inner = el?.firstElementChild;
    if (!el || !parent || !(inner instanceof HTMLElement)) return;
    const update = () => setOverflowing(inner.offsetWidth > parent.clientWidth + 1);
    update();
    const observer = new ResizeObserver(update);
    observer.observe(parent);
    observer.observe(inner);
    if (document.fonts?.ready) document.fonts.ready.then(update).catch(() => {});
    return () => observer.disconnect();
  }, [children]);

  return <span ref={ref} className={className} data-overflowing={overflowing || undefined}><span>{children}</span>{overflowing && <span aria-hidden="true">{children}</span>}</span>;
}

export default function MusicWidget() {
  const { track, audioQuality, playing, buffering, currentTime, duration, muted, queue, queueIndex, previous, next, toggle, toggleMute, setExpanded } = usePlayer();
  return <section className={styles.widget} aria-label="Music player">
    <div className={styles.mobileSeek}><WaveformSeek compact /></div>
    <button className={styles.art} type="button" onClick={() => track && setExpanded(true)} disabled={!track} aria-label="Open full screen player">{track?.coverUrl ? <LoadingImage sizes="54px" src={sizedPlayerCoverArtUrl(track.coverUrl, 108)} alt="" /> : <Disc3 />}</button>
    <button className={styles.skip} type="button" onClick={previous} disabled={!track} aria-label="Previous track"><SkipBack /></button>
    <button className={styles.play} type="button" onClick={toggle} disabled={!track} aria-label={playing ? "Pause" : "Play"}>{playing ? <Pause /> : <Play />}</button>
    <button className={styles.skip} type="button" onClick={next} disabled={queueIndex < 0 || queueIndex >= queue.length - 1} aria-label="Next track"><SkipForward /></button>
    <div className={styles.track}><button className={styles.identity} type="button" disabled={!track} onClick={() => setExpanded(true)} aria-label={track ? `Open player for ${track.title}` : "No track selected"}><strong><Marquee className={styles.titleMarquee}>{track?.title || "Nothing playing"}</Marquee></strong><small><Marquee className={styles.metaMarquee}>{buffering ? "Preparing audio stream" : track ? <>{track.artist || "Unknown artist"}{track.album ? ` · ${track.album}` : ""}<span className={styles.quality}>{audioQualityLabel(audioQuality)}</span></> : "Choose a track from Browse"}</Marquee></small></button>
      <div className={styles.timeline}><time>{stamp(currentTime)}</time><WaveformSeek compact /><time>{stamp(duration)}</time></div>
    </div>
    <button className={styles.mute} type="button" onClick={toggleMute} disabled={!track} aria-label={muted ? "Unmute" : "Mute"}>{muted ? <VolumeX /> : <Volume2 />}</button>
  </section>;
}
