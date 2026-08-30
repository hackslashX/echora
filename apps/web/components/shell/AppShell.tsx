"use client";

import { useRouter } from "next/navigation";
import { ReactNode, useEffect, useState } from "react";
import AppHeader from "./AppHeader";
import styles from "./AppShell.module.css";
import PageGrid from "./PageGrid";
import type { GridDefinition } from "./gridGeometry";

type ShellUser = { username: string; display_name: string; onboarding_complete: boolean };
let cachedUser: ShellUser | null = null;

export default function AppShell({ title, footer, children, flush = false, fullPage = false, grid, breadcrumb = false, onboarding = false, animate = false }: { title: string; footer: ReactNode; children: ReactNode; flush?: boolean; fullPage?: boolean; grid?: GridDefinition; breadcrumb?: boolean; onboarding?: boolean; animate?: boolean }) {
  const router = useRouter();
  const [user, setUser] = useState<ShellUser | null>(cachedUser);
  const [transition, setTransition] = useState<"entering" | "idle" | "leaving">(grid || animate ? "entering" : "idle");
  useEffect(() => {
    const accept = (value: ShellUser) => {
      cachedUser = value;
      if (onboarding && value.onboarding_complete) { router.replace("/home"); return; }
      if (!onboarding && !value.onboarding_complete) { router.replace("/connect"); return; }
      setUser(value);
    };
    const update = (event: Event) => {
      const detail = (event as CustomEvent<Partial<ShellUser>>).detail;
      if (cachedUser) accept({ ...cachedUser, ...detail });
    };
    window.addEventListener("echora:user-update", update);
    if (cachedUser) {
      if (onboarding && cachedUser.onboarding_complete) router.replace("/home");
      else if (!onboarding && !cachedUser.onboarding_complete) router.replace("/connect");
    } else fetch("/analysis/auth/me").then(response => {
      if (response.status === 401) { router.replace("/login"); return null; }
      if (!response.ok) throw new Error("Could not verify session");
      return response.json();
    }).then(value => value && accept(value)).catch(() => router.replace("/login"));
    return () => window.removeEventListener("echora:user-update", update);
  }, [onboarding, router]);

  useEffect(() => {
    if (transition !== "entering") return;
    const timer = window.setTimeout(() => setTransition("idle"), 300);
    return () => window.clearTimeout(timer);
  }, [transition]);

  useEffect(() => {
    const leave = () => setTransition("leaving");
    window.addEventListener("echora:navigation-leave", leave);
    return () => window.removeEventListener("echora:navigation-leave", leave);
  }, []);

  if (!user) return <main className={styles.loading}>ECHORA</main>;
  const displayName = user.display_name || user.username;
  const initials = displayName.split(/\s+/).filter(Boolean).slice(0, 2).map(part => part[0]).join("").toUpperCase();

  return <main className={`${styles.canvas} ${styles[transition]}`}>
    <section className={styles.unsupported}><strong>THIS VIEW NEEDS MORE ROOM</strong><p>Resize the window to at least 900 pixels wide or open Echora on a larger screen.</p></section>
    <section className={styles.frame}>
      {grid && <PageGrid columns={grid.columns} rows={grid.rows} phase={transition} />}
      <AppHeader title={title} breadcrumb={breadcrumb} displayName={displayName} initials={initials || "EC"} />
      <div className={`${styles.body} ${flush ? styles.flush : ""} ${fullPage ? styles.fullPage : ""}`}>{children}</div>
      {footer}
    </section>
  </main>;
}
