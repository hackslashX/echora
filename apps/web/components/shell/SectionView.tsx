import CopyrightFooter from "./CopyrightFooter";
import AppShell from "./AppShell";
import EdgeLines from "./EdgeLines";
import styles from "./SectionView.module.css";

export default function SectionView({ name, description }: { name: string; description: string }) {
  const footer = <CopyrightFooter />;
  return <AppShell title={name} footer={footer} grid={{ columns: [1, 1, 1], rows: [1, 1, 1] }} breadcrumb><section className={styles.content}><EdgeLines /><p>ECHORA / {name}</p><h1>{name}</h1><span>{description}</span></section></AppShell>;
}
