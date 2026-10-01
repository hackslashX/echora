"use client";

import { useEffect, useState } from "react";
import { Plug } from "lucide-react";
import CardHeader from "../ui/CardHeader";
import styles from "./SettingsView.module.css";

type Key = { id: string; label: string; prefix: string; expires_at: string; last_used_at: string | null; status: "active" | "expired" | "revoked" };
type Profile = {
  enabled: boolean; connection_id: string | null; musical_weight: number;
  musical_semantic_weight: number; missing_lyrics: "audio" | "exclude";
  max_per_artist: number; key_expiry_days: number; serve_lyrics: boolean;
  include_translations: boolean; lyrics_format: "ttml" | "lrc";
};
type Settings = Profile & { keys: Key[] };
type GeneratedKey = { secret: string; expires_at: string };
const initial: Profile = { enabled: false, connection_id: null, musical_weight: 80, musical_semantic_weight: 70, missing_lyrics: "audio", max_per_artist: 2, key_expiry_days: 90, serve_lyrics: true, include_translations: true, lyrics_format: "ttml" };
const endpoint = "/analysis/settings/integrations/navidrome";

async function request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(endpoint + path, { method, cache: "no-store", ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }) });
  const result = response.status === 204 ? null : await response.json();
  if (!response.ok) throw new Error(typeof result?.detail === "string" ? result.detail : "Could not update the Navidrome plugin integration");
  return result;
}

export default function NavidromePluginSettings({ connectionId }: { connectionId: string | null }) {
  const [profile, setProfile] = useState<Profile>(initial);
  const [keys, setKeys] = useState<Key[]>([]);
  const [generated, setGenerated] = useState<GeneratedKey | null>(null);
  const [label, setLabel] = useState("Navidrome");
  const [expiry, setExpiry] = useState(90);
  const [apiUrl, setApiUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function load() {
    const { keys: storedKeys, ...storedProfile } = await request<Settings>("");
    setProfile(storedProfile); setKeys(storedKeys); setLoaded(true);
    return storedProfile;
  }
  useEffect(() => {
    let cancelled = false;
    request<Settings>("").then(({ keys: storedKeys, ...storedProfile }) => {
      if (cancelled) return;
      setProfile(storedProfile); setKeys(storedKeys); setLoaded(true);
      setExpiry(storedProfile.key_expiry_days);
      setApiUrl(`${window.location.origin}/analysis/integrations/navidrome/v1`);
    }).catch(reason => { if (!cancelled) setError(reason.message); });
    return () => { cancelled = true; };
  }, []);

  async function run(action: () => Promise<void>) {
    setBusy(true); setError(""); setMessage("");
    try { await action(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not update integration"); }
    finally { setBusy(false); }
  }
  function save(enabled = profile.enabled) {
    return run(async () => {
      const result = await request<{ generated_key: GeneratedKey | null }>("", "PUT", { ...profile, enabled, connection_id: connectionId });
      if (result.generated_key) setGenerated(result.generated_key);
      await load(); setMessage(enabled ? "Plugin settings saved" : "Plugin integration disabled");
    });
  }
  function update<K extends keyof Profile>(key: K, value: Profile[K]) { setProfile(current => ({ ...current, [key]: value })); }
  const disabled = busy || !loaded;

  return <section className={styles.pluginSettings}>
    <CardHeader as="h3" icon={<Plug />} title="Echora Navidrome plugin" description="Sonic discovery and enriched lyrics using this Echora account’s library and preferences." />
    <button type="button" className={styles.switch} role="switch" aria-checked={profile.enabled} disabled={disabled || (!connectionId && !profile.enabled)} onClick={() => save(!profile.enabled)}><span>Enable Navidrome plugin access</span><b>{profile.enabled ? "ON" : "OFF"}</b></button>
    <p className={styles.layoutHelp}>Connect Navidrome above, then enable this integration to generate your first key. Everyone using the key in Navidrome receives this account’s results.</p>
    {profile.connection_id && connectionId !== profile.connection_id && <p className={styles.error}>The connected server has changed. Saving these settings binds the integration to the current connection and revokes its old keys.</p>}
    <form onSubmit={event => { event.preventDefault(); save(); }}>
      <fieldset disabled={disabled} className={styles.pluginFields}>
        <label className={styles.selectPreference}><span>Musical / lyrical balance</span><input aria-label="Musical match percentage" type="range" min="0" max="100" step="1" value={profile.musical_weight} onChange={event => update("musical_weight", Number(event.target.value))} /><small>{profile.musical_weight}% musical · {100 - profile.musical_weight}% lyrical</small></label>
        <label className={styles.selectPreference}><span>Musical evidence balance</span><input aria-label="Musical semantics percentage" type="range" min="0" max="100" step="1" value={profile.musical_semantic_weight} onChange={event => update("musical_semantic_weight", Number(event.target.value))} /><small>{profile.musical_semantic_weight}% musical character · {100 - profile.musical_semantic_weight}% acoustic detail</small></label>
        <label className={styles.selectPreference}><span>Missing lyrical analysis</span><select value={profile.missing_lyrics} onChange={event => update("missing_lyrics", event.target.value as Profile["missing_lyrics"])}><option value="audio">Use musical evidence only</option><option value="exclude">Exclude tracks without lyrical analysis</option></select></label>
        <label className={styles.selectPreference}><span>Maximum tracks per artist</span><input type="number" min="1" max="20" required value={profile.max_per_artist} onChange={event => update("max_per_artist", Number(event.target.value))} /></label>
        <label className={styles.selectPreference}><span>Default key expiry (days)</span><input type="number" min="1" max="3650" required value={profile.key_expiry_days} onChange={event => update("key_expiry_days", Number(event.target.value))} /></label>
        <button type="button" className={styles.switch} role="switch" aria-checked={profile.serve_lyrics} onClick={() => update("serve_lyrics", !profile.serve_lyrics)}><span>Provide Echora lyrics</span><b>{profile.serve_lyrics ? "ON" : "OFF"}</b></button>
        <button type="button" className={styles.switch} role="switch" aria-checked={profile.include_translations} disabled={!profile.serve_lyrics} onClick={() => update("include_translations", !profile.include_translations)}><span>Include available translations</span><b>{profile.include_translations ? "ON" : "OFF"}</b></button>
        <label className={styles.selectPreference}><span>Lyrics format</span><select disabled={!profile.serve_lyrics} value={profile.lyrics_format} onChange={event => update("lyrics_format", event.target.value as Profile["lyrics_format"])}><option value="ttml">Enhanced timing and translation tracks (TTML)</option><option value="lrc">Line timing and language variants (LRC)</option></select><small>Enhanced lyrics require a compatible Navidrome version and client. Existing transcripts and translations are served without starting new analysis.</small></label>
      </fieldset>
      <button disabled={disabled || (!connectionId && profile.enabled)}>SAVE PLUGIN SETTINGS</button>
    </form>
    <div className={styles.pluginSetup}>
      <label className={styles.selectPreference}><span>Plugin API URL</span><input readOnly value={apiUrl} /></label>
      <p>Install echora.ndp in Navidrome, enable it, and set its URL and API key. Put echora first in Agents for discovery and LyricsPriority for lyrics.</p>
    </div>
    {generated && <div className={styles.generatedKey} role="status">
      <strong>Copy this key now. It is shown only once.</strong>
      <input aria-label="New Navidrome API key" readOnly value={generated.secret} />
      <small>Expires {new Date(generated.expires_at).toLocaleDateString()}</small>
      <div className={styles.formActions}><button type="button" onClick={() => run(async () => { await navigator.clipboard.writeText(generated.secret); setMessage("API key copied"); })}>COPY KEY</button><button type="button" className={styles.secondary} onClick={() => setGenerated(null)}>DISMISS</button></div>
    </div>}
    <form onSubmit={event => { event.preventDefault(); run(async () => { const next = await request<GeneratedKey>("/keys", "POST", { label, expiry_days: expiry }); setGenerated(next); await load(); setMessage("API key generated"); }); }}>
      <label><span>Key label</span><input required maxLength={100} value={label} onChange={event => setLabel(event.target.value)} /></label>
      <label><span>Key expiry (days)</span><input type="number" min="1" max="3650" required value={expiry} onChange={event => setExpiry(Number(event.target.value))} /></label>
      <button disabled={disabled || !profile.enabled || !label.trim() || generated !== null}>GENERATE ANOTHER KEY</button>
    </form>
    {keys.length > 0 && <ul className={styles.integrationKeys}>{keys.map(key => <li key={key.id}><div><strong>{key.label}</strong><small>{key.prefix}… · {key.status} · expires {new Date(key.expires_at).toLocaleDateString()}</small><small>Last used: {key.last_used_at ? new Date(key.last_used_at).toLocaleString() : "Never"}</small></div>{key.status !== "revoked" && <button type="button" className={styles.secondaryAction} disabled={busy} onClick={() => run(async () => { await request(`/keys/${key.id}`, "DELETE"); await load(); setMessage("API key revoked"); })}>REVOKE</button>}</li>)}</ul>}
    {message && <p className={styles.message} role="status">{message}</p>}
    {error && <p className={styles.error} role="alert">{error}</p>}
  </section>;
}
