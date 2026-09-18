import type { ButtonHTMLAttributes, ReactNode } from "react";
import styles from "./ActionButton.module.css";

type ActionButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  children: ReactNode;
  tone?: "primary" | "secondary";
};

export default function ActionButton({ children, className = "", tone = "secondary", ...props }: ActionButtonProps) {
  return <button {...props} className={`${styles.button} ${styles[tone]} ${className}`}>{children}</button>;
}
