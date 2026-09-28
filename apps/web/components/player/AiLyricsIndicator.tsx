"use client";

import { useId } from "react";
import { Sparkles } from "lucide-react";
import styles from "./AiLyricsIndicator.module.css";

type Props = { transcribed: boolean; translatedLanguages: string[] };

export default function AiLyricsIndicator({ transcribed, translatedLanguages }: Props) {
  const id = useId();
  const languages = [...new Set(translatedLanguages)];
  if (!transcribed && !languages.length) return null;
  return <>
    <button type="button" className={styles.indicator} popoverTarget={id} aria-label="AI processing applied to this song" title="AI processing details"><Sparkles aria-hidden="true" /></button>
    <div id={id} popover="auto" className={styles.popup} aria-label="AI processing details">
      <h2>AI processing</h2>
      {transcribed && <section><h3>Transcription</h3><p>AI transcribed the original lyrics from audio.</p></section>}
      {languages.length > 0 && <section><h3>Translation</h3><p>AI translated the lyrics into {languages.map(language => {
        try { return new Intl.DisplayNames(["en"], { type: "language" }).of(language) || language; }
        catch { return language; }
      }).join(", ")}.</p></section>}
      <p className={styles.warning}>AI-generated results can contain errors or misinterpret the song&apos;s meaning.</p>
    </div>
  </>;
}
