export type PlaybackQuality = "original" | "320" | "120";
export type PlaybackPreferences = {
  quality: PlaybackQuality;
  wavesEnabled: boolean;
  bassReactivity: number;
  vocalReactivity: number;
  trebleReactivity: number;
};

export const defaultPlaybackPreferences: PlaybackPreferences = {
  quality: "original",
  wavesEnabled: true,
  bassReactivity: 1,
  vocalReactivity: 1,
  trebleReactivity: 1,
};

const storageKey = "echora:playback-preferences";

export function readPlaybackPreferences(): PlaybackPreferences {
  if (typeof window === "undefined") return defaultPlaybackPreferences;
  try { return { ...defaultPlaybackPreferences, ...JSON.parse(localStorage.getItem(storageKey) || "{}") }; }
  catch { return defaultPlaybackPreferences; }
}

export function writePlaybackPreferences(value: PlaybackPreferences) {
  localStorage.setItem(storageKey, JSON.stringify(value));
  window.dispatchEvent(new CustomEvent("echora:playback-preferences", { detail: value }));
}

export function streamUrlForQuality(url: string, quality: PlaybackQuality) {
  const next = new URL(url, window.location.origin);
  next.searchParams.set("quality", quality);
  return `${next.pathname}${next.search}`;
}
