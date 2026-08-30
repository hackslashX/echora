"use client";

import { AudioLines, BrainCircuit, Clock3, Gauge, MicVocal, Radio, Server, ShieldCheck, SlidersHorizontal, UserRound } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import AppShell from "../shell/AppShell";
import CopyrightFooter from "../shell/CopyrightFooter";
import { trackTemplate } from "../shell/gridGeometry";
import { readCompactLayoutPreference, writeCompactLayoutPreference } from "../shell/layoutPreference";
import { defaultPlaybackPreferences, PlaybackPreferences, readPlaybackPreferences, writePlaybackPreferences } from "../player/playbackPreferences";
import styles from "./SettingsView.module.css";

type Tab = "server" | "lastfm" | "playback" | "models" | "appearance" | "timezone" | "account" | "oidc";
type Settings = {
  profile: { username: string; email: string; display_name: string; is_admin: boolean };
  timezone: string;
  navidrome: { id: string; url: string; username: string } | null;
  lastfm: { connected: boolean; username?: string };
  models: { karaoke_processing_enabled: boolean; hum_processing_enabled: boolean };
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
  const [forceCompactLayout, setForceCompactLayout] = useState(readCompactLayoutPreference);
  const [karaokeEnabled, setKaraokeEnabled] = useState(true);
  const [humEnabled, setHumEnabled] = useState(true);

  function apply(value: Settings) {
    setSettings(value); setServerUrl(value.navidrome?.url || ""); setServerUsername(value.navidrome?.username || "");
    setLastfmUsername(value.lastfm.username || ""); setTimezone(value.timezone); setDisplayName(value.profile.display_name);
    setKaraokeEnabled(value.models.karaoke_processing_enabled);
    setHumEnabled(value.models.hum_processing_enabled);
    setPlayback(readPlaybackPreferences());
    setForceCompactLayout(readCompactLayoutPreference());
  }
  function load() { api<Settings>("/settings").then(apply).catch(reason => setError(reason.message)); }
  function loadOidc() { api<OidcSettings>("/settings/oidc").then(setOidc).catch(reason => setError(reason.message)); }
  useEffect(load, []);
  function savePlayback(next: PlaybackPreferences) { setPlayback(next); writePlaybackPreferences(next); setMessage("Playback preferences saved"); setError(""); }
  function saveAnimationSpeed(next: PlaybackPreferences["animationSpeed"]) {
    savePlayback({ ...playback, animationSpeed: next });
  }
  function saveCompactLayout(next: boolean) {
    setForceCompactLayout(next);
    writeCompactLayoutPreference(next);
    setMessage(next ? "Compact Metro interface enabled for this browser" : "Automatic layout selection restored");
    setError("");
    window.setTimeout(() => window.location.reload(), 120);
  }
  async function saveKaraokeProcessing(next: boolean) {
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await api<{ pending: number }>("/settings/models/karaoke", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ enabled: next }) });
      setKaraokeEnabled(next); setMessage(next ? `Karaoke processing enabled. ${result.pending} tracks will be processed during the next Entire Library sync.` : "Karaoke processing disabled. Existing karaoke lyrics remain available.");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not save karaoke processing"); }
    finally { setBusy(false); }
  }
  async function saveHumProcessing(next: boolean) {
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await api<{ pending: number }>("/settings/models/hum", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ enabled: next }) });
      setHumEnabled(next); setMessage(next ? `Hum processing enabled. ${result.pending} tracks will be indexed during the next Entire Library sync.` : "Hum processing disabled. Existing melody contours remain searchable.");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not save hum processing"); }
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
    ...(settings?.profile.is_admin ? [{ id: "models" as Tab, label: "Models", note: "Analysis processing rules", icon: BrainCircuit }] : []),
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
        {tab === "models" && settings?.profile.is_admin && <section className={styles.preferences}><header><BrainCircuit /><div><h2>Model processing</h2><p>Choose which application-wide analysis jobs run during library synchronization.</p></div></header><section className={styles.modelRule}><div><MicVocal /><span><strong>Karaoke timing</strong><small>Generate syllable timing for tracks with synced lyrics.</small></span></div><button className={styles.switch} disabled={busy} onClick={() => saveKaraokeProcessing(!karaokeEnabled)}><span>Process karaoke lyrics during library sync</span><b>{karaokeEnabled ? "ON" : "OFF"}</b></button><p>Disabling this skips new alignment work. Existing karaoke lyrics remain available.</p></section><section className={styles.modelRule}><div><AudioLines /><span><strong>Query by humming</strong><small>Extract melody contours from the full mix, vocals, and accompaniment.</small></span></div><button className={styles.switch} disabled={busy} onClick={() => saveHumProcessing(!humEnabled)}><span>Process hum-search melodies during library sync</span><b>{humEnabled ? "ON" : "OFF"}</b></button><p>Disabling this skips new contour extraction. Tracks already indexed remain searchable.</p></section></section>}
        {tab === "appearance" && <section className={styles.preferences}><header><Gauge /><div><h2>Application motion</h2><p>Set the pace of page transitions, controls, fullscreen views, lyrics, and background movement.</p></div></header><label className={styles.selectPreference}><span>Animation speed</span><select value={playback.animationSpeed} onChange={event => saveAnimationSpeed(event.target.value as PlaybackPreferences["animationSpeed"])}><option value="slow">Slow</option><option value="normal">Normal</option><option value="fast">Fast</option></select><small>This preference applies across the entire application.</small></label><button className={styles.switch} onClick={() => saveCompactLayout(!forceCompactLayout)}><span>Always use compact Metro interface</span><b>{forceCompactLayout ? "ON" : "AUTO"}</b></button><small className={styles.layoutHelp}>Stored only in this browser. Auto uses the desktop interface at 1200 × 720 and above.</small><section className={styles.preferenceSection}><header><AudioLines /><div><h3>Background waves</h3><p>Control backdrop style, wave visibility, and frequency-band response.</p></div></header><label className={styles.selectPreference}><span>Backdrop style</span><select value={playback.backdropPreset} onChange={event => savePlayback({ ...playback, backdropPreset: event.target.value as PlaybackPreferences["backdropPreset"] })}><option value="waves">PS3 waves</option><option value="oscilloscope">Oscilloscope</option><option value="void">Void tunnel</option><option value="curtain">Digital curtain</option><option value="ascii">ASCII dance</option></select><small>All styles react to the playing track and follow its color palette.</small></label><label className={styles.selectPreference}><span>Wave frame rate</span><select value={playback.waveFrameRate} onChange={event => savePlayback({ ...playback, waveFrameRate: event.target.value as PlaybackPreferences["waveFrameRate"] })}><option value="30">30 FPS</option><option value="60">60 FPS</option><option value="uncapped">Uncapped</option></select><small>Stored in this browser so each device can use an appropriate rendering load.</small></label><button className={styles.switch} onClick={() => savePlayback({ ...playback, wavesEnabled: !playback.wavesEnabled })}><span>Background wave animation</span><b>{playback.wavesEnabled ? "ON" : "OFF"}</b></button><div className={styles.waveControls}>{([['bassReactivity','Bass'],['vocalReactivity','Vocals'],['trebleReactivity','Treble']] as const).map(([key,label]) => <label key={key}><span><b>{label}</b><output>{Math.round(playback[key] * 100)}%</output></span><input disabled={!playback.wavesEnabled} type="range" min="0" max="2" step="0.05" value={playback[key]} onChange={event => savePlayback({ ...playback, [key]: Number(event.target.value) })} /></label>)}</div></section></section>}
        {tab === "timezone" && <form onSubmit={saveTimezone}><header><Clock3 /><div><h2>Timezone</h2><p>Listening periods use this timezone rather than the server clock.</p></div></header><label><span>IANA timezone</span><select value={timezone} onChange={event => setTimezone(event.target.value)}>{!zones.includes(timezone) && <option value={timezone}>{timezone}</option>}{zones.map(zone => <option key={zone}>{zone}</option>)}</select></label><button disabled={busy || !timezoneCanSave}>SAVE TIMEZONE</button></form>}
        {tab === "account" && <div className={styles.account}><form onSubmit={saveProfile}><header><UserRound /><div><h2>User profile</h2><p>Your email is your fixed username. Your display name can be changed.</p></div></header><label><span>Email and username</span><input disabled value={settings?.profile.email || settings?.profile.username || ""} readOnly /></label><label><span>Display name</span><input required value={displayName} onChange={event => setDisplayName(event.target.value)} /></label><button disabled={busy || !profileCanSave}>SAVE PROFILE</button></form></div>}
        {tab === "oidc" && settings?.profile.is_admin && <div className={styles.oidcAdmin}><header><ShieldCheck /><div><h2>OIDC administration</h2><p>Provider credentials come from the container environment. Manage who Echora may provision.</p></div></header>{oidc && <><dl><div><dt>Issuer</dt><dd>{oidc.issuer || "Not configured"}</dd></div><div><dt>Verified email required</dt><dd>{oidc.require_verified_email ? "Yes" : "No"}</dd></div></dl><button className={styles.policy} onClick={() => updateOidc(() => api("/settings/oidc/policy", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ auto_provision: !oidc.auto_provision }) }), oidc.auto_provision ? "Automatic provisioning disabled" : "Automatic provisioning enabled")}><span>Automatically provision new OIDC users</span><b>{oidc.auto_provision ? "ON" : "OFF"}</b></button><form className={styles.allow} onSubmit={addAllowedEmail}><label><span>Explicitly approve email</span><input type="email" required value={allowedEmail} onChange={event => setAllowedEmail(event.target.value)} placeholder="person@example.com" /></label><button disabled={busy || !allowedEmail.trim()}>ADD USER</button></form>{oidc.allowed_emails.length > 0 && <section className={styles.pending}><h3>Approved emails</h3>{oidc.allowed_emails.map(email => <article key={email}><span>{email}</span><button onClick={() => updateOidc(() => api(`/settings/oidc/allowed-emails/${encodeURIComponent(email)}`, { method: "DELETE" }), "Approval removed")}>REMOVE</button></article>)}</section>}<section className={styles.users}><h3>Users</h3>{oidc.users.map(item => <article key={item.id}><div><strong>{item.display_name}</strong><small>{item.email}</small></div><button className={item.is_admin ? styles.selected : ""} disabled={item.email === settings.profile.email} onClick={() => updateOidc(() => api(`/settings/oidc/users/${item.id}`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ is_admin: !item.is_admin }) }), item.is_admin ? "Administrator removed" : "Administrator granted")}>{item.is_admin ? "ADMIN" : "USER"}</button><button className={item.is_blocked ? styles.blocked : ""} disabled={item.email === settings.profile.email} onClick={() => updateOidc(() => api(`/settings/oidc/users/${item.id}`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ is_blocked: !item.is_blocked }) }), item.is_blocked ? "User unblocked" : "User blocked")}>{item.is_blocked ? "UNBLOCK" : "BLOCK"}</button></article>)}</section></>}</div>}
        {message && <p className={styles.message}>{message}</p>}{error && <p className={styles.error}>{error}</p>}
      </section>
    </main>
  </AppShell>;
}
