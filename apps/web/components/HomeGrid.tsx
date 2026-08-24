import { LibraryBig, Orbit, RefreshCw, Settings, WandSparkles } from "lucide-react";
import AppShell from "./shell/AppShell";
import styles from "./home/HomeMenu.module.css";
import CopyrightFooter from "./shell/CopyrightFooter";
import TransitionLink from "./shell/TransitionLink";
import { trackTemplate } from "./shell/gridGeometry";

const items = [
  { label: "Browse", note: "Processed tracks", href: "/library", position: "a", Icon: LibraryBig },
  { label: "Curate", note: "Build living playlists", href: "/curate", position: "b", Icon: WandSparkles },
  { label: "Galaxy", note: "Explore embeddings", href: "/galaxy", position: "c", Icon: Orbit },
  { label: "Sync", note: "Update your library", href: "/sync", position: "d", Icon: RefreshCw },
  { label: "Settings", note: "Server and models", href: "/settings", position: "e", Icon: Settings },
];

export default function HomeGrid() {
  const footer = <CopyrightFooter />;
  const columns = [1, 1, 1, 1, 1];
  const rows = [1, 1, 1];
  return <AppShell title="Home" footer={footer} flush fullPage grid={{ columns, rows }}>
    <section className={styles.grid} style={{ gridTemplateColumns: trackTemplate(columns, 180), gridTemplateRows: trackTemplate(rows, 152) }} aria-label="Main menu">
      {items.map((item, index) => <TransitionLink key={item.label} href={item.href} className={`${styles.tile} ${styles[item.position]}`}>
        <span>0{index + 1}</span><item.Icon className={styles.icon} strokeWidth={1.35} aria-hidden="true" /><div><strong>{item.label}</strong><small>{item.note}</small></div><b>↗</b>
      </TransitionLink>)}
    </section>
  </AppShell>;
}
