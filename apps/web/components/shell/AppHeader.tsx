"use client";

import { LogOut, X } from "lucide-react";
import { useEffect, useState } from "react";
import styles from "./AppHeader.module.css";
import TransitionLink from "./TransitionLink";

type Props = { title: string; displayName?: string; initials?: string; breadcrumb?: boolean };

export default function AppHeader({ title, displayName = "Echora", initials = "EC", breadcrumb = false }: Props) {
  const [accountOpen, setAccountOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);

  useEffect(() => {
    if (!accountOpen) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") setAccountOpen(false); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [accountOpen]);

  async function logout() {
    setLoggingOut(true);
    try { await fetch("/analysis/auth/logout", { method: "POST" }); }
    finally { window.location.assign(new URL("/login", window.location.origin)); }
  }

  return <header className={styles.header}>
    <div className={styles.brand}>ECHORA<span className={styles.note} aria-hidden="true">♪</span></div>
    <div className={`${styles.location} ${accountOpen ? styles.accountOpen : ""}`}>
      <button className={styles.profile} type="button" aria-expanded={accountOpen} aria-controls="account-menu" onClick={() => setAccountOpen(true)}>
        <span className={styles.avatar}>{initials}</span><strong>{displayName}</strong>
      </button>
      <div className={styles.menuViewport}>
        <div className={styles.navigationRow}>
          <strong className={styles.title}>{breadcrumb && <><TransitionLink href="/home">HOME</TransitionLink><span>/</span></>}{title.toUpperCase()}</strong>
        </div>
        <div className={styles.accountMenu} id="account-menu" aria-hidden={!accountOpen}>
          <div className={styles.accountActions}>
            <button type="button" onClick={logout} disabled={loggingOut}><LogOut />{loggingOut ? "LOGGING OUT" : "LOG OUT"}</button>
            <button className={styles.dismiss} type="button" aria-label="Close user menu" onClick={() => setAccountOpen(false)}><X /></button>
          </div>
        </div>
      </div>
    </div>
  </header>;
}
