"use client";

import { AudioLines, Clock3, MicVocal, Radio, Server, ShieldCheck, SlidersHorizontal, UserRound } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import AppShell from "../shell/AppShell";
import CopyrightFooter from "../shell/CopyrightFooter";
import { trackTemplate } from "../shell/gridGeometry";
import { defaultPlaybackPreferences, PlaybackPreferences, readPlaybackPreferences, writePlaybackPreferences } from "../player/playbackPreferences";
import styles from "./SettingsView.module.css";

type Tab = "server" | "lastfm" | "playback" | "models" | "appearance" | "timezone" | "account" | "oidc";
type Settings = {
  profile: { username: string; email: string; display_name: string; is_admin: boolean };
  timezone: string;
  navidrome: { id: string; url: string; username: string } | null;
  lastfm: { connected: boolean; username?: string };
  models: { karaoke_bound_to_synced_lines: boolean };
};
type OidcSettings = { configured: boolean; issuer?: string; require_verified_email: boolean; auto_provision: boolean; users: { id: string; email: string; display_name: string; is_admin: boolean; is_blocked: boolean }[]; allowed_emails: string[] };

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/analysis${path}`, options);
  const body = response.status === 204 ? null : await response.json();
  if (!response.ok) throw new Error(body?.detail || "The request failed");
  return body as T;
}

const zones = ["UTC", "America/Los_Angeles", "America/Denver", "America/Chicago", "America/New_York", "America/Toronto", "America/Sao_Paulo", "Europe/London", "Europe/Paris", "Europe/Berlin", "Europe/Warsaw", "Africa/Johannesburg", "Asia/Dubai", "Asia/Kolkata", "Asia/Bangkok", "Asia/Shanghai", "Asia/Tokyo", "Asia/Seoul", "Australia/Sydney", "Pacific/Auckland"];

export default function SettingsView() {
  const [tab, setTab] = useState<Tab>("server");
  const [settings, setSettings] = useState<Settings | null>(null);
  const [serverUrl, setServerUrl] = useState("");
  const [serverUsername, setServerUsername] = useState("");
  const [serverPassword, setServerPassword] = useState("");
  const [lastfmUsername, setLastfmUsername] = useState("");
  const [lastfmKey, setLastfmKey] = useState("");
  const [timezone, setTimezone] = useState("UTC");
  const [displayName, setDisplayName] = useState("");
  const [oidc, setOidc] = useState<OidcSettings | null>(null);
  const [allowedEmail, setAllowedEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [playback, setPlayback] = useState<PlaybackPreferences>(defaultPlaybackPreferences);
  const [karaokeBounded, setKaraokeBounded] = useState(true);

  function apply(value: Settings) {
    setSettings(value); setServerUrl(value.navidrome?.url || ""); setServerUsername(value.navidrome?.username || "");
    setLastfmUsername(value.lastfm.username || ""); setTimezone(value.timezone); setDisplayName(value.profile.display_name);
    setKaraokeBounded(value.models.karaoke_bound_to_synced_lines);
  }
  function load() { api<Settings>("/settings").then(apply).catch(reason => setError(reason.message)); }
  function loadOidc() { api<OidcSettings>("/settings/oidc").then(setOidc).catch(reason => setError(reason.message)); }
  useEffect(load, []);
  useEffect(() => { const frame = requestAnimationFrame(() => setPlayback(readPlaybackPreferences())); return () => cancelAnimationFrame(frame); }, []);
  function savePlayback(next: PlaybackPreferences) { setPlayback(next); writePlaybackPreferences(next); setMessage("Playback preferences saved"); setError(""); }
  async function saveKaraokeProcessing(next: boolean) {
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await api<{ pending: number }>("/settings/models/karaoke", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ bound_to_synced_lines: next }) });
      setKaraokeBounded(next); setMessage(`Karaoke processing updated. ${result.pending} tracks need this variant and will be processed during the next Entire Library sync.`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not save karaoke processing"); }
    finally { setBusy(false); }
  }

  async function submit(action: () => Promise<unknown>, success: string) {
    setBusy(true); setError(""); setMessage("");
    try { await action(); setMessage(success); load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not save settings"); }
    finally { setBusy(false); }
  }
  const serverCanSave = Boolean(serverUrl.trim() && serverUsername.trim() && serverPassword);
  const lastfmCanSave = Boolean(lastfmUsername.trim() && lastfmKey);
  const timezoneCanSave = Boolean(settings && timezone && timezone !== settings.timezone);
  const profileCanSave = Boolean(settings && displayName.trim() && displayName.trim() !== settings.profile.display_name);

  function saveServer(event: FormEvent) { event.preventDefault(); if (!serverCanSave) return; submit(() => api("/settings/navidrome", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ url: serverUrl, username: serverUsername, password: serverPassword }) }), "Navidrome connection verified and saved").then(() => setServerPassword("")); }
  function saveLastFm(event: FormEvent) { event.preventDefault(); if (!lastfmCanSave) return; submit(() => api("/settings/lastfm", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ username: lastfmUsername, api_key: lastfmKey }) }), "Last.fm history connection verified").then(() => setLastfmKey("")); }
  function saveTimezone(event: FormEvent) { event.preventDefault(); if (!timezoneCanSave) return; submit(() => api("/settings/timezone", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ timezone }) }), "Timezone saved"); }
  function saveProfile(event: FormEvent) { event.preventDefault(); if (!profileCanSave) return; submit(() => api("/settings/profile", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ display_name: displayName }) }), "Profile saved"); }
  function updateOidc(action: () => Promise<unknown>, success: string) { submit(action, success).then(loadOidc); }
  function addAllowedEmail(event: FormEvent) { event.preventDefault(); if (!allowedEmail.trim()) return; updateOidc(() => api("/settings/oidc/allowed-emails", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ email: allowedEmail }) }), "User approved for OIDC sign-in"); setAllowedEmail(""); }

  const columns = [0.27, 0.04, 0.69];
  const tabs: { id: Tab; label: string; note: string; icon: typeof Server }[] = [
    { id: "server", label: "Sync server", note: "Navidrome connection", icon: Server },
    { id: "lastfm", label: "Last.fm", note: "Listening history", icon: Radio },
    { id: "playback", label: "Playback", note: "Audio quality and streaming", icon: SlidersHorizontal },
    { id: "models", label: "Models", note: "Analysis processing rules", icon: MicVocal },
    { id: "appearance", label: "Appearance", note: "Visual and motion settings", icon: AudioLines },
    { id: "timezone", label: "Timezone", note: "Local listening periods", icon: Clock3 },
    { id: "account", label: "Account", note: "Email and display name", icon: UserRound },
    ...(settings?.profile.is_admin ? [{ id: "oidc" as Tab, label: "OIDC", note: "Provisioning and access", icon: ShieldCheck }] : []),
  ];
  return <AppShell title="Settings" footer={<CopyrightFooter />} breadcrumb flush fullPage grid={{ columns, rows: [1] }}>
    <main className={styles.page} style={{ gridTemplateColumns: trackTemplate(columns, 180), gridTemplateRows: trackTemplate([1], 152) }}>
      <aside className={styles.tabs}><header><h1>Settings</h1><p>Playback, appearance, connections, and account preferences.</p></header><nav>{tabs.map(item => <button key={item.id} className={tab === item.id ? styles.active : ""} onClick={() => { setTab(item.id); setError(""); setMessage(""); if (item.id === "oidc") loadOidc(); }}><item.icon /><span><strong>{item.label}</strong><small>{item.note}</small></span></button>)}</nav></aside>
      <section className={styles.content}>
        {tab === "server" && <form onSubmit={saveServer}><header><Server /><div><h2>Sync server</h2><p>Update the Navidrome server used for synchronization and playlist publishing.</p></div></header><label><span>Server URL</span><input type="url" required value={serverUrl} onChange={event => setServerUrl(event.target.value)} /></label><label><span>Username</span><input required value={serverUsername} onChange={event => setServerUsername(event.target.value)} /></label><label><span>Password</span><input type="password" required value={serverPassword} onChange={event => setServerPassword(event.target.value)} placeholder="Required to verify changes" /></label><button disabled={busy || !serverCanSave}>VERIFY + SAVE</button></form>}
        {tab === "lastfm" && <form onSubmit={saveLastFm}><header><Radio /><div><h2>Last.fm integration</h2><p>Connect listening history for familiarity mixes and time-of-day curations.</p></div></header><div className={styles.connection}><span>{settings?.lastfm.connected ? "CONNECTED" : "NOT CONNECTED"}</span><strong>{settings?.lastfm.username || "No Last.fm user"}</strong></div><label><span>Last.fm username</span><input required value={lastfmUsername} onChange={event => setLastfmUsername(event.target.value)} /></label><label><span>API key</span><input type="password" required value={lastfmKey} onChange={event => setLastfmKey(event.target.value)} placeholder="Stored encrypted" /></label><div className={styles.formActions}><button disabled={busy || !lastfmCanSave}>VERIFY + SAVE</button>{settings?.lastfm.connected && <button type="button" className={styles.secondary} onClick={() => submit(() => api("/settings/lastfm", { method: "DELETE" }), "Last.fm disconnected")}>DISCONNECT</button>}</div></form>}
        {tab === "playback" && <section className={styles.preferences}><header><SlidersHorizontal /><div><h2>Playback</h2><p>Choose the stream sent by Navidrome. Original uses the source file without bitrate reduction.</p></div></header><label className={styles.selectPreference}><span>Music transcoding</span><select value={playback.quality} onChange={event => savePlayback({ ...playback, quality: event.target.value as PlaybackPreferences["quality"] })}><option value="original">Original</option><option value="320">320 kbps</option><option value="120">120 kbps</option></select><small>Original keeps the source quality. Lower bitrates use less bandwidth.</small></label></section>}
        {tab === "models" && <section className={styles.preferences}><header><MicVocal /><div><h2>Karaoke processing</h2><p>Choose whether FA-Kara may align freely across the song or must keep each lyric line inside the timing window supplied by Navidrome.</p></div></header><button className={styles.switch} disabled={busy || !settings?.profile.is_admin} onClick={() => saveKaraokeProcessing(!karaokeBounded)}><span>Bound karaoke to original line windows</span><b>{karaokeBounded ? "ON" : "OFF"}</b></button><p>ON is the safer default. It prevents syllables from drifting into neighboring lines. Echora keeps both bounded and unbounded results. Changing this rule reuses the matching variant when it exists; the next Entire Library sync creates any missing variants.</p>{!settings?.profile.is_admin && <p>Only an administrator can change shared model processing rules.</p>}</section>}
        {tab === "appearance" && <section className={styles.preferences}><header><AudioLines /><div><h2>Wave animation</h2><p>Control the background waves and how strongly each frequency band reacts to music.</p></div></header><button className={styles.switch} onClick={() => savePlayback({ ...playback, wavesEnabled: !playback.wavesEnabled })}><span>Background wave animation</span><b>{playback.wavesEnabled ? "ON" : "OFF"}</b></button><div className={styles.waveControls}>{([['bassReactivity','Bass'],['vocalReactivity','Vocals'],['trebleReactivity','Treble']] as const).map(([key,label]) => <label key={key}><span><b>{label}</b><output>{Math.round(playback[key] * 100)}%</output></span><input disabled={!playback.wavesEnabled} type="range" min="0" max="2" step="0.05" value={playback[key]} onChange={event => savePlayback({ ...playback, [key]: Number(event.target.value) })} /></label>)}</div></section>}
        {tab === "timezone" && <form onSubmit={saveTimezone}><header><Clock3 /><div><h2>Timezone</h2><p>Listening periods use this timezone rather than the server clock.</p></div></header><label><span>IANA timezone</span><select value={timezone} onChange={event => setTimezone(event.target.value)}>{!zones.includes(timezone) && <option value={timezone}>{timezone}</option>}{zones.map(zone => <option key={zone}>{zone}</option>)}</select></label><button disabled={busy || !timezoneCanSave}>SAVE TIMEZONE</button></form>}
        {tab === "account" && <div className={styles.account}><form onSubmit={saveProfile}><header><UserRound /><div><h2>User profile</h2><p>Your email is your fixed username. Your display name can be changed.</p></div></header><label><span>Email and username</span><input disabled value={settings?.profile.email || settings?.profile.username || ""} readOnly /></label><label><span>Display name</span><input required value={displayName} onChange={event => setDisplayName(event.target.value)} /></label><button disabled={busy || !profileCanSave}>SAVE PROFILE</button></form></div>}
        {tab === "oidc" && settings?.profile.is_admin && <div className={styles.oidcAdmin}><header><ShieldCheck /><div><h2>OIDC administration</h2><p>Provider credentials come from the container environment. Manage who Echora may provision.</p></div></header>{oidc && <><dl><div><dt>Issuer</dt><dd>{oidc.issuer || "Not configured"}</dd></div><div><dt>Verified email required</dt><dd>{oidc.require_verified_email ? "Yes" : "No"}</dd></div></dl><button className={styles.policy} onClick={() => updateOidc(() => api("/settings/oidc/policy", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ auto_provision: !oidc.auto_provision }) }), oidc.auto_provision ? "Automatic provisioning disabled" : "Automatic provisioning enabled")}><span>Automatically provision new OIDC users</span><b>{oidc.auto_provision ? "ON" : "OFF"}</b></button><form className={styles.allow} onSubmit={addAllowedEmail}><label><span>Explicitly approve email</span><input type="email" required value={allowedEmail} onChange={event => setAllowedEmail(event.target.value)} placeholder="person@example.com" /></label><button disabled={busy || !allowedEmail.trim()}>ADD USER</button></form>{oidc.allowed_emails.length > 0 && <section className={styles.pending}><h3>Approved emails</h3>{oidc.allowed_emails.map(email => <article key={email}><span>{email}</span><button onClick={() => updateOidc(() => api(`/settings/oidc/allowed-emails/${encodeURIComponent(email)}`, { method: "DELETE" }), "Approval removed")}>REMOVE</button></article>)}</section>}<section className={styles.users}><h3>Users</h3>{oidc.users.map(item => <article key={item.id}><div><strong>{item.display_name}</strong><small>{item.email}</small></div><button className={item.is_admin ? styles.selected : ""} disabled={item.email === settings.profile.email} onClick={() => updateOidc(() => api(`/settings/oidc/users/${item.id}`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ is_admin: !item.is_admin }) }), item.is_admin ? "Administrator removed" : "Administrator granted")}>{item.is_admin ? "ADMIN" : "USER"}</button><button className={item.is_blocked ? styles.blocked : ""} disabled={item.email === settings.profile.email} onClick={() => updateOidc(() => api(`/settings/oidc/users/${item.id}`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ is_blocked: !item.is_blocked }) }), item.is_blocked ? "User unblocked" : "User blocked")}>{item.is_blocked ? "UNBLOCK" : "BLOCK"}</button></article>)}</section></>}</div>}
        {message && <p className={styles.message}>{message}</p>}{error && <p className={styles.error}>{error}</p>}
      </section>
    </main>
  </AppShell>;
}
