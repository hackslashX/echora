"use client";

import { TriangleAlert } from "lucide-react";
import { useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useDialogFocus } from "../shell/useDialogFocus";
import ActionButton from "../ui/ActionButton";
import CardHeader from "../ui/CardHeader";
import styles from "./FullSyncWarning.module.css";

type Props = { onClose: () => void; onConfirm: (verifyAudioHashes: boolean) => void };

export default function FullSyncWarning({ onClose, onConfirm }: Props) {
  const [verifyAudioHashes, setVerifyAudioHashes] = useState(true);
  const dialog = useRef<HTMLElement>(null);
  useDialogFocus(dialog, true, onClose);

  return createPortal(<div className={styles.scrim} onMouseDown={event => {
    if (event.target === event.currentTarget) onClose();
  }}>
    <section ref={dialog} tabIndex={-1} className={styles.dialog} role="alertdialog" aria-modal="true" aria-labelledby="full-sync-title" aria-describedby="full-sync-description">
      <CardHeader icon={<TriangleAlert aria-hidden="true" />} title={<span id="full-sync-title">Sync the entire library?</span>} />
      <div id="full-sync-description" className={styles.description}>
        <p>Refresh metadata and lyrics, fill missing analysis, and generate missing translations for your configured language pairs.</p>
        <label className={styles.hashOption}><input type="checkbox" checked={verifyAudioHashes} onChange={event => setVerifyAudioHashes(event.target.checked)} /><span>Verify audio hashes</span></label>
        <p>{verifyAudioHashes ? "Download source audio to verify track identity. This uses more bandwidth and time." : "Reuse known track identities without downloading audio just for hash comparison. Audio replaced under the same Navidrome ID may go undetected. New tracks and missing audio analysis can still require downloads."}</p>
        <p className={styles.note}>Translations use the enabled External AI endpoint and configured language pairs. Provider charges may apply. Existing valid translations and analysis are reused.</p>
      </div>
      <footer className={styles.actions}>
        <ActionButton type="button" onClick={onClose}>Go back</ActionButton>
        <ActionButton type="button" tone="primary" onClick={() => onConfirm(verifyAudioHashes)}>Start entire-library sync</ActionButton>
      </footer>
    </section>
  </div>, document.body);
}
