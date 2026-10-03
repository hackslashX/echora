"use client";

import { Sparkles } from "lucide-react";
import { Button } from "../ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "../ui/dialog";

type Props = { transcribed: boolean; translatedLanguages: string[]; motionArtwork?: boolean };

export default function AiLyricsIndicator({
  transcribed,
  translatedLanguages,
  motionArtwork = false,
}: Props) {
  const languages = [...new Set(translatedLanguages)];
  if (!transcribed && !languages.length && !motionArtwork) return null;
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label="AI processing applied to this song"
          title="AI processing details"
        >
          <Sparkles />
        </Button>
      </DialogTrigger>
      <DialogContent className="z-[1200]">
        <DialogHeader>
          <DialogTitle>AI processing</DialogTitle>
          <DialogDescription>AI-generated results can contain errors.</DialogDescription>
        </DialogHeader>
        {transcribed && (
          <section>
            <h3>Transcription</h3>
            <p>AI transcribed the original lyrics from audio.</p>
          </section>
        )}
        {languages.length > 0 && (
          <section>
            <h3>Translation</h3>
            <p>
              AI translated the lyrics into{" "}
              {languages
                .map((language) => {
                  try {
                    return (
                      new Intl.DisplayNames(["en"], { type: "language" }).of(language) || language
                    );
                  } catch {
                    return language;
                  }
                })
                .join(", ")}
              .
            </p>
          </section>
        )}
        {motionArtwork && (
          <section>
            <h3>Motion artwork</h3>
            <p>
              AI generated this video from the album cover. It may contain visual mistakes or differ
              from the original artwork.
            </p>
          </section>
        )}
      </DialogContent>
    </Dialog>
  );
}
