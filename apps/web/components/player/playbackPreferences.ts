export type BackdropPreset = "waves" | "oscilloscope" | "void" | "curtain" | "ascii" | "roots" | "lightningfall" | "meshgrid" | "clouds";
export type PlaybackQuality = "original" | "320" | "120";
export type PlaybackPreferences = {
  quality: PlaybackQuality;
  wavesEnabled: boolean;
  backdropPreset: BackdropPreset;
  bassReactivity: number;
  vocalReactivity: number;
  trebleReactivity: number;
  animationSpeed: "slow" | "normal" | "fast";
  waveFrameRate: "30" | "60" | "uncapped";
  karaokeHighlightStyle: "syllable" | "lava";
};

export const defaultPlaybackPreferences: PlaybackPreferences = {
  quality: "original",
  wavesEnabled: true,
  backdropPreset: "waves",
  bassReactivity: 1,
  vocalReactivity: 1,
  trebleReactivity: 1,
  animationSpeed: "normal",
  waveFrameRate: "30",
  karaokeHighlightStyle: "lava",
};

const storageKey = "echora:playback-preferences";

export function readPlaybackPreferences(): PlaybackPreferences {
  if (typeof window === "undefined") return defaultPlaybackPreferences;
  try {
    const stored = JSON.parse(localStorage.getItem(storageKey) || "{}");
    if (stored.backdropPreset === "retrotrain") stored.backdropPreset = "lightningfall";
    return { ...defaultPlaybackPreferences, ...stored };
  } catch { return defaultPlaybackPreferences; }
}

export function writePlaybackPreferences(value: PlaybackPreferences) {
  localStorage.setItem(storageKey, JSON.stringify(value));
  window.dispatchEvent(new CustomEvent("echora:playback-preferences", { detail: value }));
}

export function streamUrlForQuality(url: string, quality: PlaybackQuality) {
  const next = new URL(url, window.location.origin);
  next.searchParams.set("quality", quality);
  next.searchParams.set("cache", "player");
  if (next.origin !== window.location.origin) return next.toString();
  return `${next.pathname}${next.search}`;
}
