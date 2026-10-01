"use client";

import { Sparkles } from "lucide-react";
import { Button } from "../ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "../ui/dialog";

type Props = { transcribed: boolean; translatedLanguages: string[] };

export default function AiLyricsIndicator({ transcribed, translatedLanguages }: Props) {
  const languages = [...new Set(translatedLanguages)];
  if (!transcribed && !languages.length) return null;
  return <Dialog><DialogTrigger asChild><Button variant="ghost" size="icon" aria-label="AI processing applied to this song" title="AI processing details"><Sparkles /></Button></DialogTrigger><DialogContent className="z-[1200]"><DialogHeader><DialogTitle>AI processing</DialogTitle><DialogDescription>AI-generated results can contain errors or misinterpret the song&apos;s meaning.</DialogDescription></DialogHeader>{transcribed && <section><h3>Transcription</h3><p>AI transcribed the original lyrics from audio.</p></section>}{languages.length > 0 && <section><h3>Translation</h3><p>AI translated the lyrics into {languages.map(language => {
    try { return new Intl.DisplayNames(["en"], { type: "language" }).of(language) || language; }
    catch { return language; }
  }).join(", ")}.</p></section>}</DialogContent></Dialog>;
}
