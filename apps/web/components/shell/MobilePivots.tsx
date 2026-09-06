import styles from "./MobilePivots.module.css";

type Pivot<Key extends string> = {
  key: Key;
  label: string;
  count?: number;
};

export default function MobilePivots<Key extends string>({ label, active, items, onChange }: { label: string; active: Key; items: Pivot<Key>[]; onChange: (key: Key) => void }) {
  return <nav className={styles.pivots} aria-label={label}>
    {items.map(item => <button key={item.key} type="button" className={active === item.key ? styles.active : ""} onClick={() => onChange(item.key)}>
      {item.label}{item.count !== undefined && <b>{item.count}</b>}
    </button>)}
  </nav>;
}
