export type GridDefinition = { columns: number[]; rows: number[] };

export function normalizeWeights(weights: number[]) {
  const safe = weights.map(weight => Number.isFinite(weight) && weight > 0 ? weight : 0);
  const total = safe.reduce((sum, weight) => sum + weight, 0);
  if (total === 0) return weights.map(() => 1 / Math.max(weights.length, 1));
  return safe.map(weight => weight / total);
}

export function trackTemplate(weights: number[], fixed: number) {
  const tracks = normalizeWeights(weights).map(weight => `minmax(0,${weight}fr)`).join(" ");
  return `${fixed}px ${tracks} ${fixed}px`;
}

export function linePositions(weights: number[], fixed: number) {
  const normalized = normalizeWeights(weights);
  let cumulative = 0;
  const internal = normalized.slice(0, -1).map(weight => {
    cumulative += weight;
    return `calc(${fixed}px + (100% - ${fixed * 2}px) * ${cumulative})`;
  });
  return ["0px", `${fixed}px`, ...internal, `calc(100% - ${fixed}px)`, "100%"];
}
