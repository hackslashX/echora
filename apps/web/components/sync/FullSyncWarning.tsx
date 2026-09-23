"use client";

import { TriangleAlert } from "lucide-react";
import { useRef } from "react";
import { createPortal } from "react-dom";
import { useDialogFocus } from "../shell/useDialogFocus";
import ActionButton from "../ui/ActionButton";
import CardHeader from "../ui/CardHeader";
import styles from "./FullSyncWarning.module.css";

type Props = { onClose: () => void; onConfirm: () => void };

export default function FullSyncWarning({ onClose, onConfirm }: Props) {
  const dialog = useRef<HTMLElement>(null);
  useDialogFocus(dialog, true, onClose);

  return createPortal(<div className={styles.scrim} onMouseDown={event => {
    if (event.target === event.currentTarget) onClose();
  }}>
    <section ref={dialog} tabIndex={-1} className={styles.dialog} role="alertdialog" aria-modal="true" aria-labelledby="full-sync-title" aria-describedby="full-sync-description">
      <CardHeader icon={<TriangleAlert aria-hidden="true" />} title={<span id="full-sync-title">Recheck the entire library?</span>} />
      <div id="full-sync-description" className={styles.description}>
        <p>By default, Echora re-fetches every song from Navidrome and computes its SHA-256 content hash to verify track identity. This can take time and use substantial bandwidth.</p>
        <p>Valid existing analysis is reused. Only missing or outdated analysis is processed.</p>
        <p className={styles.note}>A configured recheck interval may skip recently verified, unchanged songs.</p>
      </div>
      <footer className={styles.actions}>
        <ActionButton type="button" onClick={onClose}>Go back</ActionButton>
        <ActionButton type="button" tone="primary" onClick={onConfirm}>Start entire-library sync</ActionButton>
      </footer>
    </section>
  </div>, document.body);
}
