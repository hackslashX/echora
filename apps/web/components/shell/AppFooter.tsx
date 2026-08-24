import { ReactNode } from "react";
import styles from "./AppFooter.module.css";

export default function AppFooter({ children, marker, pinned = false, aside }: { children: ReactNode; marker: ReactNode; pinned?: boolean; aside?: ReactNode }) {
  return <footer className={styles.footer}><div className={`${styles.box} ${pinned ? styles.pinned : ""}`}>{children}<div className={styles.marker}>{marker}</div></div>{aside && <div className={styles.aside}>{aside}</div>}</footer>;
}
