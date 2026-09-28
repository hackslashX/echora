"use client";

import { Languages, Server } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import CardHeader from "../ui/CardHeader";
import ClearTranslationsWarning from "./ClearTranslationsWarning";
import styles from "./ExternalAISettings.module.css";
import settingsStyles from "./SettingsView.module.css";

type LanguagePair = { source: string; target: string };
type Configuration = { enabled: boolean; url: string; model: string; prompt: string; language_pairs: LanguagePair[]; has_key: boolean };
const endpoint = "/analysis/settings/external-ai";
const normalizeTag = (value: string) => value.trim().replaceAll("_", "-").toLowerCase();

function validate(value: Configuration, section: "endpoint" | "translation"): string {
  if (section === "endpoint" && value.url) {
    try {
      const url = new URL(value.url);
      if (!/^https?:$/.test(url.protocol) || !url.hostname || url.username || url.password || /[\s\x00-\x1f\\?#]/.test(value.url) || /https?:\/\/[^/]*@/i.test(value.url)) throw new Error();
    } catch { return "Enter an HTTP(S) API base URL without credentials, spaces, query parameters or a fragment."; }
  }
  if (section === "endpoint") return value.enabled && !value.url ? "Enter an API URL before enabling External AI." : "";
  if (!value.prompt.trim()) return "Enter a translation prompt.";
  const seen = new Set<string>();
  for (const pair of value.language_pairs) {
    const source = normalizeTag(pair.source), target = normalizeTag(pair.target);
    if (![source, target].every(tag => /^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$/.test(tag))) return "Use language tags such as ja, en or pt-BR for every source and target.";
    if (source === target) return "Source and target languages must differ.";
    const key = `${source}:${target}`;
    if (seen.has(key)) return "Remove duplicate language pairs.";
    seen.add(key);
  }
  return "";
}

async function request(options: RequestInit | undefined, section: "/endpoint" | "/translation"): Promise<Partial<Configuration>> {
  const response = await fetch(endpoint + section, { ...options, cache: "no-store", credentials: "same-origin" });
  // Never display response bodies: validation payloads must not expose credentials.
  if (!response.ok) {
    if (response.status === 401) throw new Error("Your session expired. Sign in again.");
    if (response.status === 403) throw new Error("Administrator access is required.");
    if (response.status === 422) throw new Error("Invalid External AI settings. Check the URL, prompt and language pairs.");
    throw new Error("Could not access External AI settings. Try again.");
  }
  const body = await response.json();
  return section === "/endpoint"
    ? { enabled: body.enabled, url: body.url, has_key: body.has_key }
    : { model: body.model, prompt: body.prompt, language_pairs: body.language_pairs };
}

export default function ExternalAISettings() {
  return <div><SettingsSection section="endpoint" /><SettingsSection section="translation" /></div>;
}

function SettingsSection({ section }: { section: "endpoint" | "translation" }) {
  const [value, setValue] = useState<Configuration | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearError, setClearError] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    request({ signal: controller.signal }, `/${section}`).then(result => { if (!controller.signal.aborted) setValue({ enabled: false, url: "", has_key: false, model: "", prompt: "", language_pairs: [], ...result }); })
      .catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Could not load settings."); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [attempt, section]);

  function update(patch: Partial<Configuration>) {
    setValue(current => current ? { ...current, ...patch } : current);
    setMessage(""); setError("");
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!value || saving) return;
    setMessage("");
    const invalid = validate(value, section);
    if (invalid) { setError(invalid); return; }
    setSaving(true); setError("");
    const payload = section === "endpoint" ? {
      enabled: value.enabled, url: value.url,
      ...(clearKey ? { api_key: "" } : apiKey ? { api_key: apiKey } : {}),
    } : {
      model: value.model.trim(), prompt: value.prompt.trim(),
      language_pairs: value.language_pairs.map(pair => ({ source: normalizeTag(pair.source), target: normalizeTag(pair.target) })),
    };
    try {
      const result = await request({ method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }, `/${section}`);
      setValue(current => current ? { ...current, ...result } : current); setApiKey(""); setClearKey(false);
      setMessage("External AI settings saved.");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not save settings. Try again."); }
    finally { setSaving(false); }
  }

  async function clearTranslations() {
    if (saving) return;
    setClearError("");
    setSaving(true); setError(""); setMessage("");
    try {
      const response = await fetch(`${endpoint}/translations`, { method: "DELETE", credentials: "same-origin" });
      if (response.status === 409) throw new Error("Wait for active sync and lyrics jobs to stop, then try again.");
      if (!response.ok) throw new Error("Could not clear translations.");
      const result = await response.json();
      window.dispatchEvent(new Event("echora:translations-cleared"));
      setConfirmClear(false);
      setMessage(`Cleared ${result.deleted} translations. Save any prompt changes before running sync.`);
    } catch (reason) { setClearError(reason instanceof Error ? reason.message : "Could not clear translations."); }
    finally { setSaving(false); }
  }

  return <form className={styles.form} onSubmit={save} aria-busy={loading || saving}>
    {loading ? <p role="status" className={settingsStyles.layoutHelp}>Loading External AI settings…</p> : value && <>
      <fieldset className={styles.fields} disabled={saving}>
        {section === "endpoint" && <section className={settingsStyles.preferenceSection} aria-labelledby="external-ai-endpoint-title">
          <CardHeader icon={<Server />} title={<span id="external-ai-endpoint-title">API</span>} description="Configure the OpenAI-compatible endpoint shared by External AI features." />
          <button type="button" className={settingsStyles.switch} role="switch" aria-checked={value.enabled} onClick={() => update({ enabled: !value.enabled })}><span>Enable External AI</span><b>{value.enabled ? "ON" : "OFF"}</b></button>
          <div className={styles.endpointGrid}>
            <div>
              <label className={settingsStyles.selectPreference}><span>API base URL</span><input type="url" maxLength={2048} required={value.enabled} value={value.url} placeholder="http://localhost:8000/v1" onChange={event => update({ url: event.target.value })} aria-describedby="external-ai-url-help" /></label>
              <p id="external-ai-url-help" className={settingsStyles.layoutHelp}>/chat/completions is appended. Local HTTP is allowed; prefer HTTPS off-host.</p>
            </div>
            <div>
              <label className={settingsStyles.selectPreference} htmlFor="external-ai-key"><span>API key</span></label>
              <div className={styles.keyRow}>
                <input id="external-ai-key" type="password" autoComplete="new-password" maxLength={8192} disabled={clearKey} value={apiKey} placeholder={value.has_key && !clearKey ? "••••••••••••••••" : ""} aria-label={value.has_key ? "API key, stored key unchanged unless replaced" : "API key"} onChange={event => { setApiKey(event.target.value); setMessage(""); setError(""); }} />
                <button type="button" className={styles.compactButton} aria-pressed={clearKey} onClick={() => { setClearKey(current => !current); setApiKey(""); setMessage(""); }}>{clearKey ? "Cancel removal" : "Clear on save"}</button>
              </div>
            </div>
          </div>

        </section>}
        {section === "translation" && <section className={settingsStyles.preferenceSection} aria-labelledby="external-ai-translation-title">
          <CardHeader as="h3" icon={<Languages />} title={<span id="external-ai-translation-title">Lyrics translation</span>} description="Choose the translation model, language pairs, and instructions." />
          <p className={styles.notice}>Missing translations are generated during sync when External AI is enabled. Player display is not connected yet.</p>
          <label className={settingsStyles.selectPreference}><span>Model</span><input maxLength={200} value={value.model} onChange={event => update({ model: event.target.value })} aria-describedby="external-ai-model-help" /></label>
          <p id="external-ai-model-help" className={settingsStyles.layoutHelp}>Use the model identifier provided by your endpoint.</p>
          <section className={styles.pairs} aria-labelledby="external-ai-pairs-title"><div className={styles.pairHeading}><h4 id="external-ai-pairs-title">Language pairs</h4><button type="button" className={styles.compactButton} disabled={value.language_pairs.length >= 64} onClick={() => update({ language_pairs: [...value.language_pairs, { source: "", target: "" }] })}>+ Add</button></div>
            <div className={styles.pairList}>
              {value.language_pairs.map((pair, index) => <div className={styles.pair} key={index}>
                <label className={settingsStyles.selectPreference}><span>Source <span className={styles.srOnly}>{index + 1}</span></span><input required value={pair.source} placeholder="ja" onChange={event => update({ language_pairs: value.language_pairs.map((item, i) => i === index ? { ...item, source: event.target.value } : item) })} /></label>
                <span className={styles.arrow} aria-hidden="true">→</span>
                <label className={settingsStyles.selectPreference}><span>Target <span className={styles.srOnly}>{index + 1}</span></span><input required value={pair.target} placeholder="en" onChange={event => update({ language_pairs: value.language_pairs.map((item, i) => i === index ? { ...item, target: event.target.value } : item) })} /></label>
                <button type="button" className={settingsStyles.secondaryAction} aria-label={`Remove language pair ${index + 1}`} onClick={() => update({ language_pairs: value.language_pairs.filter((_, i) => i !== index) })}>Remove</button>
              </div>)}
            </div>
          </section>
          <label className={settingsStyles.selectPreference}><span>Instruction prompt</span><textarea required maxLength={8000} rows={5} value={value.prompt} onChange={event => update({ prompt: event.target.value })} /></label>
        </section>}
        <div className={settingsStyles.formActions}><button className={settingsStyles.primaryAction} type="submit">{saving ? "Saving…" : section === "endpoint" ? "Save API settings" : "Save translation settings"}</button></div>
        {section === "translation" && <div className={styles.clearTranslations}><button type="button" disabled={saving} onClick={() => { setClearError(""); setConfirmClear(true); }}>Clear all translations</button><p>Instance-wide. Original lyrics and karaoke timing are kept.</p></div>}
      </fieldset>
    </>}
    {confirmClear && <ClearTranslationsWarning busy={saving} error={clearError} onClose={() => setConfirmClear(false)} onConfirm={clearTranslations} />}
    {error && <p className={styles.error} role="alert">{error}</p>}
    {!loading && !value && <button type="button" onClick={() => { setLoading(true); setError(""); setAttempt(current => current + 1); }}>Retry loading</button>}
    {message && <p className={styles.success} role="status">{message}</p>}
  </form>;
}
