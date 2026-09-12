import type { ElementType, ReactNode } from "react";
import styles from "./CardHeader.module.css";

type CardHeaderProps = {
  title: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  leading?: ReactNode;
  actions?: ReactNode;
  count?: ReactNode;
  eyebrow?: ReactNode;
  as?: "h1" | "h2" | "h3";
  className?: string;
  sticky?: boolean;
};

export default function CardHeader({ title, description, icon, leading, actions, count, eyebrow, as = "h2", className = "", sticky = false }: CardHeaderProps) {
  const Heading = as as ElementType;
  return <header data-card-header className={`${styles.header} ${sticky ? styles.sticky : ""} ${className}`}>
    {leading && <div className={styles.leading}>{leading}</div>}
    {icon && <div className={styles.icon}>{icon}</div>}
    <div className={styles.copy}>
      {eyebrow && <span className={styles.eyebrow}>{eyebrow}</span>}
      <Heading className={styles.title} title={typeof title === "string" ? title : undefined}>{title}</Heading>
      {description && <p className={styles.description}>{description}</p>}
    </div>
    {count != null && <strong className={styles.count}>{count}</strong>}
    {actions && <div className={styles.actions}>{actions}</div>}
  </header>;
}
