const COVER_SIZE_MIN = 64;
const COVER_SIZE_MAX = 1600;

export function coverArtUrl(connectionId: string, coverId: string, size?: number) {
  const path = `/analysis/navidrome/connections/${encodeURIComponent(connectionId)}/cover/${encodeURIComponent(coverId)}`;
  return size ? `${path}?size=${coverArtSize(size)}` : path;
}

export function sizedCoverArtUrl(url: string, size: number) {
  const parsed = new URL(url, "https://echora.invalid");
  parsed.searchParams.set("size", String(coverArtSize(size)));
  return parsed.origin === "https://echora.invalid" ? `${parsed.pathname}${parsed.search}${parsed.hash}` : parsed.toString();
}

function coverArtSize(size: number) {
  return Math.min(COVER_SIZE_MAX, Math.max(COVER_SIZE_MIN, Math.round(size)));
}
