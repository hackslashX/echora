import { TriangleAlert } from "lucide-react";
import styles from "./RecordingMatchNotice.module.css";

export default function RecordingMatchNotice({ message }: { message: string }) {
  if (!message) return null;
  return <div className={styles.notice} role="status"><TriangleAlert aria-hidden="true" /><p>{message}</p></div>;
}
