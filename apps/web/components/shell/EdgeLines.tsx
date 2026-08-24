import styles from "./EdgeLines.module.css";

export default function EdgeLines() {
  return <span className={styles.lines} aria-hidden="true"><i className={styles.top} /><i className={styles.right} /><i className={styles.bottom} /><i className={styles.left} /></span>;
}
