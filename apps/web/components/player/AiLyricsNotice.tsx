import { TriangleAlert } from "lucide-react";
import styles from "./AiLyricsNotice.module.css";

export default function AiLyricsNotice() {
  return <div className={styles.notice} role="note" aria-label="AI lyrics warning">
    <TriangleAlert className={styles.icon} aria-hidden="true" />
    <div className={styles.copy}>
      <strong className={styles.desktopCopy}>These lyrics were transcribed by AI.</strong>
      <span className={styles.desktopCopy}>The words and timing may be inaccurate.</span>
      <span className={styles.mobileCopy}>AI-transcribed lyrics may contain errors.</span>
    </div>
  </div>;
}
