export const compactLayoutStorageKey = "echora:force-compact-layout";
export const compactLayoutEvent = "echora:compact-layout";

export function readCompactLayoutPreference() {
  return typeof window !== "undefined" && localStorage.getItem(compactLayoutStorageKey) === "true";
}

export function writeCompactLayoutPreference(enabled: boolean) {
  localStorage.setItem(compactLayoutStorageKey, String(enabled));
  window.dispatchEvent(new CustomEvent(compactLayoutEvent, { detail: enabled }));
}
