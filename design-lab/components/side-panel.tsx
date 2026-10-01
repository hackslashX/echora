import type { ReactNode } from "react";
import styles from "./side-panel.module.css";

export function SidePanel({ title, actions, children }: { title: string; actions?: ReactNode; children: ReactNode }) {
  return <section className={styles.panel} aria-label={title}>
    <header className={styles.header}><h2>{title}</h2>{actions && <div className={styles.actions}>{actions}</div>}</header>
    <div className={styles.content}>{children}</div>
  </section>;
}
