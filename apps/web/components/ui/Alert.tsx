import type { ReactNode } from "react";
import { CircleAlert, Info, TriangleAlert } from "lucide-react";
import styles from "./Alert.module.css";

const ICONS = { info: Info, warning: TriangleAlert, error: CircleAlert } as const;

export default function Alert({ tone = "info", title, className, children }: {
  tone?: keyof typeof ICONS;
  title?: string;
  className?: string;
  children: ReactNode;
}) {
  const Icon = ICONS[tone];
  return <div className={[styles.alert, styles[tone], className].filter(Boolean).join(" ")} role={tone === "error" ? "alert" : "note"}>
    <Icon className={styles.icon} aria-hidden />
    <div className={styles.body}>
      {title && <strong className={styles.title}>{title}</strong>}
      <div className={styles.content}>{children}</div>
    </div>
  </div>;
}
