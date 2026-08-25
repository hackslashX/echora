"use client";

import { Disc3, Pause, Play, SkipBack, SkipForward, Volume2, VolumeX } from "lucide-react";
import LoadingImage from "../media/LoadingImage";
import { usePlayer } from "../player/PlayerProvider";
import styles from "./MusicWidget.module.css";

const stamp = (seconds: number) => {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
};

export default function MusicWidget() {
  const { track, playing, buffering, currentTime, duration, buffered, muted, queue, queueIndex, previous, next, toggle, seek, toggleMute, setExpanded } = usePlayer();
  return <section className={styles.widget} aria-label="Music player">
    <button className={styles.art} type="button" onClick={() => track && setExpanded(true)} disabled={!track} aria-label="Open full screen player">{track?.coverUrl ? <LoadingImage sizes="54px" src={track.coverUrl} alt="" /> : <Disc3 />}</button>
    <button className={styles.skip} type="button" onClick={previous} disabled={!track} aria-label="Previous track"><SkipBack /></button>
    <button className={styles.play} type="button" onClick={toggle} disabled={!track} aria-label={playing ? "Pause" : "Play"}>{playing ? <Pause /> : <Play />}</button>
    <button className={styles.skip} type="button" onClick={next} disabled={queueIndex < 0 || queueIndex >= queue.length - 1} aria-label="Next track"><SkipForward /></button>
    <div className={styles.track}><strong>{track?.title || "Nothing playing"}</strong><small>{buffering ? "Preparing audio stream" : track ? `${track.artist || "Unknown artist"}${track.album ? ` · ${track.album}` : ""}` : "Choose a track from Browse"}</small>
      <div className={styles.timeline}><time>{stamp(currentTime)}</time><div className={styles.seek}><i style={{ width: `${duration ? Math.min(100, buffered / duration * 100) : 0}%` }} /><input type="range" min="0" max={duration || 0} step="0.1" value={Math.min(currentTime, duration || 0)} onChange={event => seek(Number(event.target.value))} disabled={!track || !duration} aria-label="Seek" /></div><time>{stamp(duration)}</time></div>
    </div>
    <button className={styles.mute} type="button" onClick={toggleMute} disabled={!track} aria-label={muted ? "Unmute" : "Mute"}>{muted ? <VolumeX /> : <Volume2 />}</button>
  </section>;
}
