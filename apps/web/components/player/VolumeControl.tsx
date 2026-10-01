"use client";

import { Volume, Volume1, Volume2, VolumeX } from "lucide-react";
import { usePlayer } from "./PlayerProvider";
import { Button } from "../ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "../ui/popover";
import { Slider } from "../ui/slider";

/** Volume icon that opens a vertical level slider above it; the icon reflects the current level. */
export default function VolumeControl({ className, side = "top" }: { className?: string; side?: "top" | "bottom" }) {
  const player = usePlayer();
  const level = player.muted ? 0 : player.volume;
  const Icon = level === 0 ? VolumeX : level < .34 ? Volume : level < .67 ? Volume1 : Volume2;
  const percent = Math.round(level * 100);
  return <Popover>
    <PopoverTrigger asChild><Button variant="ghost" size="icon" className={className} disabled={!player.track} aria-label={`Volume ${percent}%`}><Icon className="size-[18px]" /></Button></PopoverTrigger>
    <PopoverContent side={side} align="center" className="flex w-12 flex-col items-center gap-2 px-0 py-3">
      <output className="text-xs tabular-nums text-muted-foreground">{percent}</output>
      {/* A rotated horizontal range: consistent across engines, unlike vertical writing-mode ranges. */}
      <div className="relative h-32 w-5">
        <Slider aria-label="Volume" aria-orientation="vertical" min={0} max={100} step={1} value={percent} onChange={event => player.setVolume(Number(event.target.value) / 100)} className="absolute top-1/2 left-1/2" style={{ width: 128, transform: "translate(-50%, -50%) rotate(-90deg)" }} />
      </div>
      <Button variant="ghost" size="icon-sm" onClick={player.toggleMute} aria-label={player.muted ? "Unmute" : "Mute"} aria-pressed={player.muted}><Icon /></Button>
    </PopoverContent>
  </Popover>;
}
