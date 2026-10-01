"use client";

import { setUrl, useSubPath } from "../shell/urlState";
import { Palette, Sparkles, BrainCircuit, Clock3, Radio, Server, ShieldCheck, SlidersHorizontal, UserRound } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import AppShell from "../shell/AppShell";
import CopyrightFooter from "../shell/CopyrightFooter";
import { defaultPlaybackPreferences, PlaybackPreferences, readPlaybackPreferences, writePlaybackPreferences } from "../player/playbackPreferences";
import { SectionHeading, Choice, ChoiceItem, Toggle } from "./Presentation";

import { Button } from "../ui/button";
import { SettingsNotice } from "./SettingsNotice";
import { RangeControl } from "./RangeControl";
import { SettingRow } from "./SettingRow";
import { SidePanel } from "../layout/side-panel";
import { Pane } from "../layout/pane";
import { Badge } from "../ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../ui/select";
import { cn } from "@/lib/utils";
import styles from "./SettingsView.module.css";
import { Input } from "../ui/input";
import { LoadingState } from "../ui/spinner";
import ExternalAISettings from "./ExternalAISettings";
import { toast } from "sonner";
import { Notice } from "../ui/notice";
import NavidromePluginSettings from "./NavidromePluginSettings";


const allTabs = ["server", "lastfm", "playback", "models", "external-ai", "appearance", "timezone", "account", "oidc"] as const;
type Tab = typeof allTabs[number];
type Settings = {
  profile: { username: string; email: string; display_name: string; is_admin: boolean };
  timezone: string;
  navidrome: { id: string; url: string; username: string } | null;
  lastfm: { connected: boolean; username?: string };
  models: { transcription_processing_enabled: boolean; karaoke_processing_enabled: boolean; hum_processing_enabled: boolean };
};
type OidcSettings = { configured: boolean; issuer?: string; require_verified_email: boolean; auto_provision: boolean; users: { id: string; email: string; display_name: string; is_admin: boolean; is_blocked: boolean }[]; allowed_emails: string[] };

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/analysis${path}`, options);
  const body = response.status === 204 ? null : await response.json();
  if (!response.ok) throw new Error(body?.detail || "The request failed");
  return body as T;
}

const descriptions: Record<Tab, string> = {
  "server": "Update the Navidrome server used for synchronization and playlist publishing.",
  "lastfm": "Connect listening history for familiarity mixes and time-of-day curations.",
  "playback": "Choose the stream sent by Navidrome.",
  "models": "Choose which application-wide analysis jobs run during library synchronization.",
  "external-ai": "Manage endpoints and AI features.",
  "appearance": "Set motion, karaoke highlights, and audio-reactive backgrounds.",
  "timezone": "Listening periods use this timezone rather than the server clock.",
  "account": "Your email is your fixed username. Your display name can be changed.",
  "oidc": "Provider credentials come from the container environment. Manage who Echora may provision."
};

const zones = ["UTC", "America/Los_Angeles", "America/Denver", "America/Chicago", "America/New_York", "America/Toronto", "America/Sao_Paulo", "Europe/London", "Europe/Paris", "Europe/Berlin", "Europe/Warsaw", "Africa/Johannesburg", "Asia/Dubai", "Asia/Kolkata", "Asia/Bangkok", "Asia/Shanghai", "Asia/Tokyo", "Asia/Seoul", "Australia/Sydney", "Pacific/Auckland"];

export default function SettingsView() {
  // The section lives in the path (/settings/appearance) so it can be linked and survives reloads.
  const requestedTab = useSubPath("settings");
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
  // Only load failures stay on the page; action results are toasts.
  const [loadError, setLoadError] = useState("");
  const [playback, setPlayback] = useState<PlaybackPreferences>(defaultPlaybackPreferences);
  const [karaokeEnabled, setKaraokeEnabled] = useState(true);
  const [transcriptionEnabled, setTranscriptionEnabled] = useState(false);
  const [humEnabled, setHumEnabled] = useState(true);

  function apply(value: Settings) {
    setSettings(value); setServerUrl(value.navidrome?.url || ""); setServerUsername(value.navidrome?.username || "");
    setLastfmUsername(value.lastfm.username || ""); setTimezone(value.timezone); setDisplayName(value.profile.display_name);
    setKaraokeEnabled(value.models.karaoke_processing_enabled);
    setHumEnabled(value.models.hum_processing_enabled);
    setTranscriptionEnabled(value.models.transcription_processing_enabled);
    setPlayback(readPlaybackPreferences());
  }
  function load() { api<Settings>("/settings").then(apply).catch(reason => setLoadError(reason.message)); }
  function loadOidc() { api<OidcSettings>("/settings/oidc").then(setOidc).catch(reason => toast.error("Could not load sign-in settings", { description: reason.message })); }
  useEffect(load, []);
  function savePlayback(next: PlaybackPreferences) { setPlayback(next); writePlaybackPreferences(next); toast.success("Playback preferences saved", { id: "playback-preferences" }); }
  function saveAnimationSpeed(next: PlaybackPreferences["animationSpeed"]) {
    savePlayback({ ...playback, animationSpeed: next });
  }
  async function saveKaraokeProcessing(next: boolean) {
    setBusy(true);
    try {
      const result = await api<{ pending: number }>("/settings/models/karaoke", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ enabled: next }) });
      setKaraokeEnabled(next); toast.success(next ? "Karaoke processing enabled" : "Karaoke processing disabled", { description: next ? `${result.pending} tracks will be processed during the next Entire Library sync.` : "Existing karaoke lyrics remain available." });
    } catch (reason) { fail("Could not save karaoke processing", reason); }
    finally { setBusy(false); }
  }
  async function saveTranscriptionProcessing(next: boolean) {
    setBusy(true);
    try {
      await api("/settings/models/transcription", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ enabled: next }) });
      setTranscriptionEnabled(next);
      toast.success(next ? "AI lyrics generation enabled" : "AI lyrics generation disabled", { description: next ? "Entire Library sync processes missing lyrics." : "The current track may finish; no further tracks will start. Existing lyrics remain available." });
    } catch (reason) { fail("Could not save lyrics processing", reason); }
    finally { setBusy(false); }
  }
  async function saveHumProcessing(next: boolean) {
    setBusy(true);
    try {
      const result = await api<{ pending: number }>("/settings/models/hum", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ enabled: next }) });
      setHumEnabled(next); toast.success(next ? "Hum processing enabled" : "Hum processing disabled", { description: next ? `${result.pending} tracks will be indexed during the next Entire Library sync.` : "Existing melody contours remain searchable." });
    } catch (reason) { fail("Could not save hum processing", reason); }
    finally { setBusy(false); }
  }

  function fail(title: string, reason: unknown) { toast.error(title, { description: reason instanceof Error ? reason.message : undefined }); }
  async function submit(action: () => Promise<unknown>, success: string) {
    setBusy(true);
    try { await action(); toast.success(success); load(); }
    catch (reason) { fail("Could not save settings", reason); }
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

  const adminTabs: Tab[] = ["models", "external-ai", "oidc"];
  const knownTab = (allTabs as readonly string[]).includes(requestedTab ?? "") ? requestedTab as Tab : "account";
  // Admin sections fall back to Account for everyone else once we know who they are.
  const tab: Tab = settings && !settings.profile.is_admin && adminTabs.includes(knownTab) ? "account" : knownTab;
  // Sign-in settings load whenever that section opens, by click or by URL.
  const oidcOpen = tab === "oidc";
  useEffect(() => {
    if (!oidcOpen) return;
    api<OidcSettings>("/settings/oidc").then(setOidc).catch(reason => toast.error("Could not load sign-in settings", { description: reason.message }));
  }, [oidcOpen]);
  const tabs: { id: Tab; label: string; group: string; icon: typeof Server }[] = [
    { id: "account", label: "Account", group: "You", icon: UserRound },
    { id: "appearance", label: "Appearance", group: "You", icon: Palette },
    { id: "playback", label: "Playback", group: "You", icon: SlidersHorizontal },
    { id: "timezone", label: "Timezone", group: "You", icon: Clock3 },
    { id: "server", label: "Music server", group: "Connections", icon: Server },
    { id: "lastfm", label: "Listening history", group: "Connections", icon: Radio },
    ...(settings?.profile.is_admin ? [
      { id: "models" as Tab, label: "Analysis models", group: "Administration", icon: BrainCircuit },
      { id: "external-ai" as Tab, label: "External AI", group: "Administration", icon: Sparkles },
      { id: "oidc" as Tab, label: "Sign-in & users", group: "Administration", icon: ShieldCheck },
    ] : []),
  ];
  const groups = Array.from(new Set(tabs.map(item => item.group)));
  const current = tabs.find(item => item.id === tab);
  function selectTab(next: Tab) { setUrl(`/settings/${next}`); }
  const navigation = <SidePanel title="Settings"><nav aria-label="Settings sections" className="grid gap-6">{groups.map(group => <div key={group}>
    <h3 className="mb-1.5 px-3 text-xs font-medium text-subtle-foreground">{group}</h3>
    <ul className="space-y-0.5">{tabs.filter(item => item.group === group).map(item => <li key={item.id}><button type="button" onClick={() => selectTab(item.id)} aria-current={tab === item.id ? "page" : undefined} className={cn("relative flex h-9 w-full items-center gap-3 px-3 text-left text-[13px] font-medium transition-colors", tab === item.id ? "bg-raised text-foreground before:absolute before:inset-y-2 before:left-0 before:w-0.5 before:bg-primary" : "text-muted-foreground hover:bg-surface hover:text-foreground")}><item.icon className={cn("size-4", tab === item.id && "text-primary")} />{item.label}</button></li>)}</ul>
  </div>)}</nav></SidePanel>;
  return <AppShell title="Settings" footer={<CopyrightFooter />}>
    <div className="grid h-full min-h-0 grid-rows-[minmax(0,1fr)] md:grid-cols-[260px_minmax(0,1fr)]">
      <div className="hidden min-h-0 border-r border-border bg-rail md:block">{navigation}</div>
      <Pane className="bg-workspace" label={current?.label || "Settings"} title={current?.label || "Settings"} subtitle={descriptions[tab]}
        actions={<>{["models", "external-ai", "oidc"].includes(tab) && <Badge variant="outline" className="h-7 gap-1.5 text-xs" title="Changes in this section apply to every Echora user"><ShieldCheck className="size-3.5 text-primary" />Admin · applies to everyone</Badge>}<Select value={tab} onValueChange={value => selectTab(value as Tab)}><SelectTrigger aria-label="Settings section" className="w-44 md:hidden"><SelectValue /></SelectTrigger><SelectContent>{tabs.map(item => <SelectItem key={item.id} value={item.id}>{item.label}</SelectItem>)}</SelectContent></Select></>}>
        <section key={tab} className={`motion-enter ${styles.form}`}>
          {loadError && !settings ? <Notice tone="error" title="Could not load settings" action={<Button variant="outline" size="sm" onClick={() => { setLoadError(""); load(); }}>Try again</Button>}>{loadError}</Notice> : !settings ? <LoadingState label="Loading settings…" /> : <>
        {tab === "external-ai" && settings?.profile.is_admin && <ExternalAISettings />}
        {tab === "server" && <form onSubmit={saveServer}><SectionHeading title="Connection credentials" /><SettingRow label={<>Server URL</>} htmlFor="settings-field-1" description="The URL of your Navidrome server, including https://."><Input id="settings-field-1" type="url" required value={serverUrl} onChange={event => setServerUrl(event.target.value)} /></SettingRow><SettingRow label={<>Username</>} htmlFor="settings-field-2" description="Your Navidrome login, not your Echora account."><Input id="settings-field-2" required value={serverUsername} onChange={event => setServerUsername(event.target.value)} /></SettingRow><SettingRow label={<>Password</>} htmlFor="settings-field-3" description="Required to verify access to your collection."><Input id="settings-field-3" type="password" required value={serverPassword} onChange={event => setServerPassword(event.target.value)} placeholder="Required to verify changes" /></SettingRow><div className={styles.actions}><Button loading={busy} disabled={!serverCanSave}>Verify and save</Button></div></form>}
        {tab === "server" && <NavidromePluginSettings connectionId={settings?.navidrome?.id ?? null} />}
        {tab === "lastfm" && <form onSubmit={saveLastFm}><SectionHeading title="Last.fm connection" /><SettingRow label="Connection" description="Listening history connection status."><span>{settings?.lastfm.connected ? "Connected" : "Not connected"}</span><p className="text-muted-foreground">{settings?.lastfm.username || "No Last.fm user"}</p></SettingRow><SettingRow label={<>Last.fm username</>} htmlFor="settings-field-4" description="The account used for listening history."><Input id="settings-field-4" required value={lastfmUsername} onChange={event => setLastfmUsername(event.target.value)} /></SettingRow><SettingRow label={<>API key</>} htmlFor="settings-field-5" description="Your Last.fm API key is stored encrypted."><Input id="settings-field-5" type="password" required value={lastfmKey} onChange={event => setLastfmKey(event.target.value)} placeholder="Stored encrypted" /></SettingRow><div className={styles.actions}><Button loading={busy} disabled={!lastfmCanSave}>Verify and save</Button>{settings?.lastfm.connected && <Button variant="outline" type="button" disabled={busy} onClick={() => submit(() => api("/settings/lastfm", { method: "DELETE" }), "Last.fm disconnected")}>Disconnect</Button>}</div></form>}
        {tab === "playback" && <section><SectionHeading title="Streaming quality" /><SettingRow label={<>Music transcoding</>} htmlFor="settings-field-6" description={<>Original keeps the source quality. Lower bitrates use less bandwidth.</>}><Choice id="settings-field-6" value={playback.quality} onChange={value => savePlayback({ ...playback, quality: value as PlaybackPreferences["quality"] })}><ChoiceItem value="original">Original</ChoiceItem><ChoiceItem value="320">320 kbps</ChoiceItem><ChoiceItem value="120">120 kbps</ChoiceItem></Choice></SettingRow></section>}
        {tab === "models" && settings?.profile.is_admin && <section>
          <SectionHeading title="Lyrics processing" />
          <SettingsNotice tone="warning" title="AI-generated lyrics">Generated words and timing may be inaccurate. Existing lyrics remain available when processing is disabled.</SettingsNotice>
          <Toggle label="AI lyrics generation" description="Use Mel-Band-Roformer and MOSS to transcribe tracks with missing lyrics. Off by default. AI words and timing may be inaccurate. Disabling prevents further tracks from starting; existing lyrics remain available." checked={transcriptionEnabled} disabled={busy} onChange={() => saveTranscriptionProcessing(!transcriptionEnabled)} />
          <Toggle label="Karaoke timing" description="Generate syllable timing for tracks with synced lyrics. Disabling skips new alignment work; existing karaoke lyrics remain available." checked={karaokeEnabled} disabled={busy} onChange={() => saveKaraokeProcessing(!karaokeEnabled)} />
          <div className={styles.group}><SectionHeading title="Melody search" /></div>
          <Toggle label="Query by humming" description="Extract melody contours from the full mix, vocals, and accompaniment. Disabling skips new contour extraction; tracks already indexed remain searchable." checked={humEnabled} disabled={busy} onChange={() => saveHumProcessing(!humEnabled)} />
        </section>}
        {tab === "appearance" && <section><SectionHeading title="Motion and interface" /><SettingRow label={<>Animation speed</>} htmlFor="settings-field-7" description={<>This preference applies across the entire application.</>}><Choice id="settings-field-7" value={playback.animationSpeed} onChange={value => saveAnimationSpeed(value as PlaybackPreferences["animationSpeed"])}><ChoiceItem value="slow">Slow</ChoiceItem><ChoiceItem value="normal">Normal</ChoiceItem><ChoiceItem value="fast">Fast</ChoiceItem></Choice></SettingRow><SettingRow label={<>Karaoke highlight style</>} htmlFor="settings-field-8" description={<>Highlight each syllable at once or fill it with a moving liquid edge. Timing stays the same. Saved in this browser.</>}><Choice id="settings-field-8" value={playback.karaokeHighlightStyle} onChange={value => savePlayback({ ...playback, karaokeHighlightStyle: value as PlaybackPreferences["karaokeHighlightStyle"] })}><ChoiceItem value="syllable">Syllable highlight</ChoiceItem><ChoiceItem value="lava">Lava fill</ChoiceItem></Choice></SettingRow><section className="pt-6"><SectionHeading title="Audio-reactive backdrop" description="Choose how the desktop background responds to the playing track and its frequency bands." /><SettingRow label={<>Backdrop style</>} htmlFor="settings-field-9" description={<>All styles use the playing track and its album-derived color palette. Backdrops are hidden in the compact mobile layout.</>}><Choice id="settings-field-9" value={playback.backdropPreset} onChange={value => savePlayback({ ...playback, backdropPreset: value as PlaybackPreferences["backdropPreset"] })}><ChoiceItem value="waves">PS3 waves</ChoiceItem><ChoiceItem value="oscilloscope">Oscilloscope</ChoiceItem><ChoiceItem value="void">Void tunnel</ChoiceItem><ChoiceItem value="curtain">Digital curtain</ChoiceItem><ChoiceItem value="ascii">ASCII dance</ChoiceItem><ChoiceItem value="roots">Living roots</ChoiceItem><ChoiceItem value="lightningfall">Lightning Fall</ChoiceItem><ChoiceItem value="meshgrid">Mesh Grid</ChoiceItem><ChoiceItem value="clouds">Storm clouds</ChoiceItem><ChoiceItem value="waterdrops">Water drops</ChoiceItem></Choice>{playback.backdropPreset === "waterdrops" && <SettingsNotice tone="info" title="Backdrop behavior">Music drives invisible drop impacts on an album-colored water surface. Bass sets impact size, vocals change drop velocity and ripple spread, and treble changes surface tension and damping. Ripples overlap and interfere, then settle when playback pauses.</SettingsNotice>}{playback.backdropPreset === "meshgrid" && <SettingsNotice tone="info" title="Backdrop behavior">A rippling triangular landscape in album-art colors. Bass raises the waves, vocals roughen the mesh, and treble lights the edges.</SettingsNotice>}{playback.backdropPreset === "lightningfall" && <SettingsNotice tone="info" title="Backdrop behavior">Dense falling trails in album-art colors. Bass and tempo drive the flow; individual frequency bands subtly vary trail length, thickness, and glow. Pausing dims the trails.</SettingsNotice>}{playback.backdropPreset === "clouds" && <SettingsNotice tone="warning" title="Flashing effects">Full-background smoke. Bass drives billowing, vocals drive cloud color, and treble lights cloud edges and soft internal lightning. Attacks in any band can trigger branching strikes. Drift follows estimated tempo. Strikes are at least 0.8 seconds apart. Contains flashes. Set all three sensitivity sliders to zero for no lightning, or turn off Animated backdrop.</SettingsNotice>}</SettingRow><SettingRow label={<>Wave frame rate</>} htmlFor="settings-field-10" description={<>Stored in this browser so each device can use an appropriate rendering load.</>}><Choice id="settings-field-10" value={playback.waveFrameRate} onChange={value => savePlayback({ ...playback, waveFrameRate: value as PlaybackPreferences["waveFrameRate"] })}><ChoiceItem value="30">30 FPS</ChoiceItem><ChoiceItem value="60">60 FPS</ChoiceItem><ChoiceItem value="uncapped">Uncapped</ChoiceItem></Choice></SettingRow><Toggle label="Animated backdrop" checked={playback.wavesEnabled} disabled={busy} onChange={() => savePlayback({ ...playback, wavesEnabled: !playback.wavesEnabled })} /><div><SettingRow label={<><b>Backdrop opacity</b><output className="font-normal tabular-nums">{Math.round(playback.backdropOpacity * 100)}%</output></>} htmlFor="settings-field-11"><RangeControl id="settings-field-11" aria-label="Backdrop opacity" min="0" max="1" step="0.05" value={playback.backdropOpacity} onChange={event => savePlayback({ ...playback, backdropOpacity: Number(event.target.value) })} /></SettingRow></div><div>{([['bassReactivity','Bass'],['vocalReactivity','Vocals'],['trebleReactivity','Treble']] as const).map(([key,label]) => <SettingRow key={key} label={<><b>{label}</b><output className="font-normal tabular-nums">{Math.round(playback[key] * 100)}%</output></>} htmlFor={`settings-${key}`}><RangeControl id={`settings-${key}`} disabled={!playback.wavesEnabled} min="0" max="2" step="0.05" value={playback[key]} onChange={event => savePlayback({ ...playback, [key]: Number(event.target.value) })} /></SettingRow>)}</div></section></section>}
        {tab === "timezone" && <form onSubmit={saveTimezone}><SectionHeading title="Listening periods" /><SettingRow label={<>IANA timezone</>} htmlFor="settings-field-13" description="Use your local timezone for listening periods."><Choice id="settings-field-13" value={timezone} onChange={value => setTimezone(value)}>{!zones.includes(timezone) && <ChoiceItem value={timezone}>{timezone}</ChoiceItem>}{zones.map(zone => <ChoiceItem key={zone} value={zone}>{zone}</ChoiceItem>)}</Choice></SettingRow><div className={styles.actions}><Button loading={busy} disabled={!timezoneCanSave}>Save timezone</Button></div></form>}
        {tab === "account" && <div className="space-y-5"><form onSubmit={saveProfile}><SectionHeading title="Profile details" /><SettingRow label={<>Email and username</>} htmlFor="settings-field-14" description="Your email is your fixed username."><Input id="settings-field-14" disabled value={settings?.profile.email || settings?.profile.username || ""} readOnly /></SettingRow><SettingRow label={<>Display name</>} htmlFor="settings-field-15" description="The name shown in your account menu."><Input id="settings-field-15" required value={displayName} onChange={event => setDisplayName(event.target.value)} /></SettingRow><div className={styles.actions}><Button loading={busy} disabled={!profileCanSave}>Save profile</Button></div></form></div>}
        {tab === "oidc" && settings?.profile.is_admin && <div>{!oidc && <LoadingState label="Loading sign-in settings…" />}{oidc && <><SectionHeading title="Provider and provisioning" /><SettingRow label="Issuer"><span className="break-all">{oidc.issuer || "Not configured"}</span></SettingRow><SettingRow label="Verified email required">{oidc.require_verified_email ? "Yes" : "No"}</SettingRow><Toggle label="Automatically provision new OIDC users" checked={oidc.auto_provision} disabled={busy} onChange={() => updateOidc(() => api("/settings/oidc/policy", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ auto_provision: !oidc.auto_provision }) }), oidc.auto_provision ? "Automatic provisioning disabled" : "Automatic provisioning enabled")} /><form className={styles.group} onSubmit={addAllowedEmail}><SectionHeading title="Sign-in approvals" /><SettingRow label={<>Explicitly approve email</>} htmlFor="settings-field-16" description="Allow this email address to sign in using OIDC."><Input id="settings-field-16" type="email" required value={allowedEmail} onChange={event => setAllowedEmail(event.target.value)} placeholder="person@example.com" /></SettingRow><div className={styles.actions}><Button loading={busy} disabled={!allowedEmail.trim()}>Add user</Button></div></form>{oidc.allowed_emails.length > 0 && <section className={styles.group}><SectionHeading title="Approved emails" count={oidc.allowed_emails.length} />{oidc.allowed_emails.map(email => <article className={styles.identity} key={email}><span className={styles.identityText}>{email}</span><Button variant="outline" aria-label={`Remove approval for ${email}`} disabled={busy} onClick={() => updateOidc(() => api(`/settings/oidc/allowed-emails/${encodeURIComponent(email)}`, { method: "DELETE" }), "Approval removed")}>Remove</Button></article>)}</section>}<section className={styles.group}><SectionHeading title="Users" count={oidc.users.length} />{oidc.users.map(item => <article className={styles.identity} key={item.id}><div className={styles.identityText}><strong>{item.display_name}</strong><small>{item.email}</small></div><div className={styles.identityActions}><Button aria-label={`${item.is_admin ? "Remove administrator from" : "Make administrator:"} ${item.email}`} variant={item.is_admin ? "secondary" : "outline"} disabled={busy || item.email === settings.profile.email} onClick={() => updateOidc(() => api(`/settings/oidc/users/${item.id}`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ is_admin: !item.is_admin }) }), item.is_admin ? "Administrator removed" : "Administrator granted")}>{item.is_admin ? "Admin" : "User"}</Button><Button aria-label={`${item.is_blocked ? "Unblock" : "Block"} ${item.email}`} variant={item.is_blocked ? "destructive" : "outline"} disabled={busy || item.email === settings.profile.email} onClick={() => updateOidc(() => api(`/settings/oidc/users/${item.id}`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ is_blocked: !item.is_blocked }) }), item.is_blocked ? "User unblocked" : "User blocked")}>{item.is_blocked ? "Unblock" : "Block"}</Button></div></article>)}</section></>}</div>}
        </>}</section>
      </Pane>
    </div>
  </AppShell>;
}
