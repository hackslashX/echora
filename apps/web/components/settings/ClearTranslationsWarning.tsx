"use client";

import { TriangleAlert } from "lucide-react";
import { useRef } from "react";
import { createPortal } from "react-dom";
import { useDialogFocus } from "../shell/useDialogFocus";
import CardHeader from "../ui/CardHeader";
import ActionButton from "../ui/ActionButton";
import styles from "./ClearTranslationsWarning.module.css";

type Props = { busy: boolean; error: string; onClose: () => void; onConfirm: () => void };

export default function ClearTranslationsWarning({ busy, error, onClose, onConfirm }: Props) {
  const dialog = useRef<HTMLElement>(null);
  const close = () => { if (!busy) onClose(); };
  useDialogFocus(dialog, true, close);
  return createPortal(<div className={styles.scrim} onMouseDown={event => { if (event.target === event.currentTarget) close(); }}>
    <section ref={dialog} tabIndex={-1} className={styles.dialog} role="alertdialog" aria-modal="true" aria-labelledby="clear-translations-title" aria-describedby="clear-translations-description" aria-busy={busy}>
      <CardHeader icon={<TriangleAlert aria-hidden="true" />} title={<span id="clear-translations-title">Clear all translations?</span>} />
      <div className={styles.description} id="clear-translations-description">
        <p>This deletes stored translations for every user. Original lyrics and karaoke timing stay unchanged.</p>
        <p>Save your new prompt before the next Entire library sync to regenerate translations. This deletion cannot be undone.</p>
      </div>
      {error && <p role="alert" className={styles.error}>{error}</p>}
      <footer className={styles.actions}>
        <ActionButton type="button" disabled={busy} onClick={close}>Keep translations</ActionButton>
        <ActionButton type="button" disabled={busy} onClick={onConfirm}>{busy ? "Clearing…" : "Clear all translations"}</ActionButton>
      </footer>
    </section>
  </div>, document.body);
}
