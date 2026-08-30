import AppFooter from "./AppFooter";
import MusicWidget from "./MusicWidget";
import styles from "./CopyrightFooter.module.css";

export default function CopyrightFooter() {
  const copyright = <div className={styles.notice}><span>© 2026 ECHORA</span><span>MUSIC INTELLIGENCE</span><span>OSS v0.1.7</span></div>;
  return <AppFooter marker={null} pinned aside={copyright}><MusicWidget /></AppFooter>;
}
