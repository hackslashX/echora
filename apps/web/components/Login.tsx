"use client";

import { ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import styles from "./Login.module.css";

export default function Login() {
  const [configured, setConfigured] = useState<boolean | null>(null);
  useEffect(() => {
    fetch("/analysis/auth/oidc/status").then(response => response.json()).then(body => setConfigured(Boolean(body.configured))).catch(() => setConfigured(false));
  }, []);
  return <main className={styles.page}><section className={styles.card}><div className={styles.brand}>ECHORA ♪</div><h1>Welcome<br />back.</h1><p>Continue through your organization&apos;s identity provider.</p><div className={styles.oidc}><ShieldCheck /><div><strong>OpenID Connect</strong><small>Your email address identifies your Echora account.</small></div></div>{configured === false && <p className={styles.error}>OIDC has not been configured for this server.</p>}<button type="button" disabled={!configured} onClick={() => { window.location.assign(new URL("/analysis/auth/oidc/start", window.location.origin)); }}>{configured === null ? "CHECKING OIDC" : "CONTINUE WITH OIDC"}</button></section></main>;
}
