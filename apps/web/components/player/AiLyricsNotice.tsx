import styles from "./AiLyricsNotice.module.css";

export default function AiLyricsNotice() {
  return <p className={styles.notice} role="note">Lyrics transcribed using AI/ML. May contain errors.</p>;
}
