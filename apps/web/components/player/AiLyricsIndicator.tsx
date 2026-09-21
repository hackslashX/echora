import { Sparkles } from "lucide-react";
import styles from "./AiLyricsIndicator.module.css";

export default function AiLyricsIndicator() {
  return <span className={styles.indicator} tabIndex={0} role="img" aria-label="AI-transcribed lyrics may contain errors">
    <Sparkles aria-hidden="true" />
    <span role="tooltip">AI-transcribed lyrics may contain errors.</span>
  </span>;
}
