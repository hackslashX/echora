import type { ReactNode } from "react";
import styles from "./page-header.module.css";
export function PageHeader({ title, description, actions }: { title: string; description: string; actions?: ReactNode }) {
  return <header className={styles.header}><div><h1>{title}</h1><p>{description}</p></div>{actions && <div className={styles.actions}>{actions}</div>}</header>;
}
