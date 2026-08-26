import type { AudioQuality } from "./PlayerProvider";

const codecName = (codec?: string) => {
  const value = codec?.trim().toUpperCase();
  return value === "M4A" ? "AAC" : value || "AUDIO";
};

export function audioQualityLabel(quality: AudioQuality | null): string {
  if (!quality) return "Reading audio quality";
  if (quality.streamQuality !== "original") return `MP3 · ${quality.streamQuality} kbps`;
  const parts = [quality.lossless ? "LOSSLESS" : codecName(quality.codec)];
  if (quality.lossless) parts.push(codecName(quality.codec));
  if (quality.bit_depth) parts.push(`${quality.bit_depth}-bit`);
  if (quality.sample_rate_hz) {
    const khz = quality.sample_rate_hz / 1000;
    parts.push(`${Number.isInteger(khz) ? khz : khz.toFixed(1)} kHz`);
  }
  if (quality.bit_rate_kbps) parts.push(`${quality.bit_rate_kbps} kbps`);
  return parts.join(" · ");
}
