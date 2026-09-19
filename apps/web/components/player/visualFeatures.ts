/** Revision 2 is a fixed, non-learned source-audio timeline with optional cached model enrichment. */
export type VisualFeatureTimeline = {
  rhythm?: DescriptorRhythm | null;
  enrichment?: VisualEnrichment;
  structureSummary?: { edges_seconds: number[]; novelty: number[] };
  revision: "2"; sample_rate: number; hop_length: number; hop_seconds: number;
  duration_seconds: number; source_offset_seconds: number; frame_count: number;
  bands: number[][]; band_centers_hz: number[]; level: number[]; centroid: number[]; flux: number[]; onset: number[];
  chroma: number[][]; pitch: number[][]; pitch_midi_start: number; waveform: number[][]; waveform_offsets_samples: number[]; waveform_window_samples: 2048;
  reactivity: number[][]; attacks: number[][]; reactivity_edges_hz: number[];
  timbre: { centroid_hz: number[]; bandwidth_hz: number[]; rolloff_hz: number[]; flatness: number[]; zcr: number[] };
  onset_times_seconds: number[]; beat_times_seconds: number[];
  tempo: { bpm: number | null; candidates_bpm: number[] };
  kernels: { kind: "fixed_nonlearned"; names: string[]; values: number[][] };
};
const record = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const number = (value: unknown, min: number, max: number): value is number => typeof value === "number" && Number.isFinite(value) && value >= min && value <= max;
const vector = (value: unknown, size: number, min = 0, max = 1): value is number[] => Array.isArray(value) && value.length === size && Array.from(value).every(item => number(item, min, max));
const matrix = (value: unknown, rows: number, columns: number, min = 0, max = 1) => Array.isArray(value) && value.length === rows && Array.from(value).every(row => vector(row, columns, min, max));
const sorted = (values: number[]) => values.every((value, index) => !index || value > values[index - 1]);

export function validateVisualFeatures(value: unknown): VisualFeatureTimeline | null {
  if (!record(value) || value.revision !== "2" || value.sample_rate !== 22050 || value.hop_length !== 512 ||
    !number(value.hop_seconds, 512 / 22050 - 1e-9, 512 / 22050 + 1e-9) || value.source_offset_seconds !== 0 ||
    !number(value.duration_seconds, Number.MIN_VALUE, 600) || !number(value.frame_count, 1, 25840) || !Number.isInteger(value.frame_count)) return null;
  const n = value.frame_count;
  // Backend emits one frame per source hop, excluding a padded endpoint.
  if (n !== Math.ceil(value.duration_seconds * 22050 / 512 - 1e-9)) return null;
  for (const key of ["level", "centroid", "flux", "onset"]) if (!vector(value[key], n)) return null;
  for (const [key, size] of [["bands", 24], ["chroma", 12], ["pitch", 84], ["reactivity", 3], ["attacks", 3]] as const) if (!matrix(value[key], n, size)) return null;
  if (value.waveform_window_samples !== 2048 || !vector(value.waveform_offsets_samples, 64, 0, 2047) || !value.waveform_offsets_samples.every((offset, index) => offset === Math.round(index * 2047 / 63))) return null;
  if (!matrix(value.waveform, n, 64, -1, 1) || value.pitch_midi_start !== 24 ||
    !vector(value.band_centers_hz, 24, 0, 11025) || !sorted(value.band_centers_hz) ||
    !vector(value.reactivity_edges_hz, 4, 0, 11025) || !value.reactivity_edges_hz.every((edge, index) => edge === [20, 250, 2000, 10000][index])) return null;
  if (!record(value.timbre)) return null;
  for (const key of ["centroid_hz", "bandwidth_hz", "rolloff_hz"]) if (!vector(value.timbre[key], n, 0, 11025)) return null;
  for (const key of ["flatness", "zcr"]) if (!vector(value.timbre[key], n)) return null;
  for (const key of ["onset_times_seconds", "beat_times_seconds"]) {
    const times = value[key];
    if (!Array.isArray(times) || times.length > n || !vector(times, times.length, 0, value.duration_seconds) || !sorted(times)) return null;
  }
  const tempo = value.tempo, kernels = value.kernels;
  if (!record(tempo) || !(tempo.bpm === null || number(tempo.bpm, Number.MIN_VALUE, 1000)) || !Array.isArray(tempo.candidates_bpm) || tempo.candidates_bpm.length > 32 || !vector(tempo.candidates_bpm, tempo.candidates_bpm.length, Number.MIN_VALUE, 1000)) return null;
  if (!record(kernels) || kernels.kind !== "fixed_nonlearned" || !Array.isArray(kernels.names) || kernels.names.length !== 4 ||
    !Array.from(kernels.names).every(name => typeof name === "string" && name.length > 0 && name.length <= 128) || !kernels.names.every((name, index) => name === ["temporal_rise", "temporal_fall", "spectral_slope", "spectral_curvature"][index]) || !Array.isArray(kernels.values) || kernels.values.length !== n || !Array.from(kernels.values).every(row => Array.isArray(row) && row.length === 4 && Array.from(row).every((cell, index) => number(cell, kernels.names instanceof Array && kernels.names[index] === "spectral_slope" ? -1 : 0, 1)))) return null;
  if (value.structure !== undefined && !validateStructure(value.structure, value.duration_seconds)) return null;
  // Whitelist fields: unbounded structure/enrichment never enters the animation loop.
  const { revision, sample_rate, hop_length, hop_seconds, duration_seconds, source_offset_seconds, frame_count, bands, band_centers_hz, level, centroid, flux, onset, chroma, pitch, pitch_midi_start, waveform, waveform_offsets_samples, waveform_window_samples, reactivity, attacks, reactivity_edges_hz, timbre, onset_times_seconds, beat_times_seconds } = value;
  const structureSummary = record(value.structure) ? { edges_seconds: value.structure.edges_seconds, novelty: value.structure.novelty } : undefined;
  return { revision, sample_rate, hop_length, hop_seconds, duration_seconds, source_offset_seconds, frame_count, bands, band_centers_hz, level, centroid, flux, onset, chroma, pitch, pitch_midi_start, waveform, waveform_offsets_samples, waveform_window_samples, reactivity, attacks, reactivity_edges_hz, timbre, onset_times_seconds, beat_times_seconds, tempo, kernels, structureSummary } as VisualFeatureTimeline;
}

export type VisualFrame = {
  trackId: string | null;
  source: { revision: "2"; sampleRate: number; hopSeconds: number; durationSeconds: number; bandCentersHz: number[]; waveformOffsetsSamples: number[]; pitchMidiStart: number } | null;
  tempoCandidatesBpm: number[];
  enrichment: { vocalActivation: number | null; melodyPreviewPitchMidi: number | null; melodySource: string | null } | null;
  structuralNovelty: number | null;
  rhythmSource: "core" | "descriptors" | null;
  active: boolean; timestamp: number; frameIndex: number; bpm: number | null; beat: boolean;
  features: { chroma: number[]; pitch: number[]; centroid: number; flux: number; onset: number; timbre: Record<keyof VisualFeatureTimeline["timbre"], number>; kernels: { names: string[]; values: number[] } } | null;
  bands: number[]; waveform: number[]; bass: number; mid: number; treble: number;
  level: number; onset: boolean; bassAttack: number; midAttack: number; trebleAttack: number;
};
export function neutralVisualFrame(timestamp = 0): VisualFrame {
  return { trackId: null, source: null, tempoCandidatesBpm: [], enrichment: null, structuralNovelty: null, rhythmSource: null, features: null, active: false, timestamp: Number.isFinite(timestamp) ? timestamp : 0, frameIndex: -1, bpm: null, beat: false, bands: Array(24).fill(0), waveform: Array(64).fill(0), bass: 0, mid: 0, treble: 0, level: 0, onset: false, bassAttack: 0, midAttack: 0, trebleAttack: 0 };
}
function crossed(times: number[], from: number, to: number) {
  let low = 0, high = times.length;
  while (low < high) { const middle = (low + high) >>> 1; if (times[middle] <= from) low = middle + 1; else high = middle; }
  return low < times.length && times[low] <= to;
}
export function visualFrameAt(timeline: VisualFeatureTimeline | null, timestamp: number, previousTime: number | null): VisualFrame {
  if (!timeline || !Number.isFinite(timestamp) || timestamp < 0 || timestamp >= timeline.duration_seconds) return neutralVisualFrame(timestamp);
  const index = Math.floor(timestamp / timeline.hop_seconds);
  if (index >= timeline.frame_count) return neutralVisualFrame(timestamp);
  const continuous = previousTime !== null && timestamp >= previousTime && timestamp - previousTime < .25;
  const changed = continuous && Math.floor(previousTime / timeline.hop_seconds) !== index;
  const [bass, mid, treble] = timeline.reactivity[index];
  const [bassAttack, midAttack, trebleAttack] = changed ? timeline.attacks[index] : [0, 0, 0];
  const vocal = timeline.enrichment?.vocal;
  const vocalWindow = vocal?.[lastAtOrBefore(vocal, timestamp, item => item.start_seconds)];
  const melody = timeline.enrichment?.melody;
  const melodyIndex = melody ? lastAtOrBefore(melody.points, timestamp, item => item.time_seconds) : -1;
  const melodyPoint = melody && melodyIndex >= 0 ? melody.points[melodyIndex] : null;
  const structure = timeline.structureSummary;
  const structureIndex = structure ? lastAtOrBefore(structure.edges_seconds, timestamp, item => item) : -1;
  return { trackId: null, source: { revision: "2", sampleRate: timeline.sample_rate, hopSeconds: timeline.hop_seconds, durationSeconds: timeline.duration_seconds, bandCentersHz: timeline.band_centers_hz, waveformOffsetsSamples: timeline.waveform_offsets_samples, pitchMidiStart: timeline.pitch_midi_start },
    tempoCandidatesBpm: timeline.rhythm ? [timeline.rhythm.bpm / 2, timeline.rhythm.bpm, timeline.rhythm.bpm * 2] : timeline.tempo.candidates_bpm,
    enrichment: { vocalActivation: vocalWindow && timestamp < vocalWindow.end_seconds ? vocalWindow.vocal_activation : null, melodyPreviewPitchMidi: melodyPoint?.pitch ?? null, melodySource: melody?.source ?? null },
    structuralNovelty: structure?.novelty[structureIndex] ?? null,
    rhythmSource: timeline.rhythm ? "descriptors" : "core", features: { chroma: timeline.chroma[index], pitch: timeline.pitch[index], centroid: timeline.centroid[index], flux: timeline.flux[index], onset: timeline.onset[index], timbre: { centroid_hz: timeline.timbre.centroid_hz[index], bandwidth_hz: timeline.timbre.bandwidth_hz[index], rolloff_hz: timeline.timbre.rolloff_hz[index], flatness: timeline.timbre.flatness[index], zcr: timeline.timbre.zcr[index] }, kernels: { names: timeline.kernels.names, values: timeline.kernels.values[index] } }, active: true, timestamp, frameIndex: index, bpm: timeline.rhythm?.bpm ?? timeline.tempo.bpm,
    beat: continuous && crossed(timeline.rhythm?.beat_times_seconds ?? timeline.beat_times_seconds, previousTime, timestamp),
    onset: continuous && crossed(timeline.onset_times_seconds, previousTime, timestamp),
    bands: timeline.bands[index], waveform: timeline.waveform[index], level: timeline.level[index], bass, mid, treble, bassAttack, midAttack, trebleAttack };
}
export function publishVisualFrame(frame: VisualFrame) {
  window.dispatchEvent(new CustomEvent("echora:visual-frame", { detail: frame }));
  // Temporary bridge for shell/Backdrop.tsx (outside the player ownership boundary).
  window.dispatchEvent(new CustomEvent("echora:audio-reactivity", { detail: frame }));
}

/** Structure is bounded and validated separately; never copied into per-frame events. */
export function validateStructure(value: unknown, duration: number): boolean {
  if (!record(value) || value.method !== "pooled_mfcc_rbf_chroma_cosine_nonlearned" || value.max_bins !== 192 || !Array.isArray(value.novelty)) return false;
  const n = value.novelty.length;
  return n >= 1 && n <= 192 && vector(value.novelty, n) && vector(value.edges_seconds, n + 1, 0, duration + 1e-6) && sorted(value.edges_seconds) && value.edges_seconds[0] === 0 && Math.abs(value.edges_seconds[n] - duration) <= 1e-6 && matrix(value.chroma_cosine, n, n) && matrix(value.mfcc_rbf, n, n);
}
export type DescriptorRhythm = { bpm: number; beat_times_seconds: number[] };
/** Only a complete, recognized, full-source descriptor may override core rhythm. */
export function descriptorRhythm(enrichment: unknown, duration: number): DescriptorRhythm | null {
  if (!record(enrichment) || !record(enrichment.descriptors)) return null;
  const envelope = enrichment.descriptors, data = envelope.descriptors;
  if (envelope.revision !== "1" || envelope.status !== "complete" || !record(data) || data.revision !== "1" ||
    !number(data.duration_seconds, 0, 600) || Math.abs(data.duration_seconds - duration) > 1 / 22050 || !record(data.rhythm)) return null;
  const rhythm = data.rhythm, beats = rhythm.beat_times_seconds;
  if (!number(rhythm.bpm, Number.MIN_VALUE, 1000) || !Array.isArray(beats) || beats.length < 2 || beats.length > 25840 || !vector(beats, beats.length, 0, duration) || !sorted(beats)) return null;
  return { bpm: rhythm.bpm, beat_times_seconds: beats };
}


type VocalWindow = { start_seconds: number; end_seconds: number; vocal_activation: number };
type MelodyData = { source: string; points: { time_seconds: number; pitch: number | null }[] };
export type VisualEnrichment = { vocal: VocalWindow[] | null; melody: MelodyData | null };
function lastAtOrBefore<T>(values: T[], time: number, timestamp: (value: T) => number): number {
  let low = 0, high = values.length;
  while (low < high) { const middle = (low + high) >>> 1; if (timestamp(values[middle]) <= time) low = middle + 1; else high = middle; }
  return low - 1;
}
/** Optional existing model outputs, never inferred from mid-band energy. Missing spans stay null. */
export function validateVisualEnrichment(value: unknown, duration: number): VisualEnrichment {
  const result: VisualEnrichment = { vocal: null, melody: null };
  if (!record(value)) return result;
  const activity = record(value.vocal_activity) ? value.vocal_activity.activity : null;
  if (record(activity) && number(activity.duration_seconds, 0, 600) && Math.abs(activity.duration_seconds - duration) < .001 &&
      Array.isArray(activity.windows) && activity.windows.length <= 4096 && activity.windows.every((item: unknown) =>
        record(item) && number(item.start_seconds, 0, duration) && number(item.end_seconds, 0, duration) && item.end_seconds > item.start_seconds && number(item.vocal_activation, 0, 1))) {
    const windows = activity.windows as VocalWindow[];
    if (sorted(windows.map(item => item.start_seconds))) result.vocal = windows;
  }
  const melody = value.melody;
  if (record(melody) && typeof melody.source === "string" && ["full-mix", "vocals", "accompaniment"].includes(melody.source) &&
      Array.isArray(melody.points) && melody.points.length > 0 && melody.points.length <= 1024 && melody.points.every((item: unknown) =>
        record(item) && number(item.time_seconds, 0, duration) && (item.pitch === null || number(item.pitch, 0, 127)))) {
    const points = melody.points as MelodyData["points"];
    if (sorted(points.map(item => item.time_seconds))) result.melody = { source: melody.source, points };
  }
  return result;
}
