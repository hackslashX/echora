"use client";

import { ChevronDown } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import styles from "./LanguagePicker.module.css";

type Props = { value: string; onChange: (value: string) => void; options: [string, string][]; ariaLabel?: string };

export default function LanguagePicker({ value, onChange, options, ariaLabel }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const click = (event: MouseEvent) => { if (container.current && !container.current.contains(event.target as Node)) setOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", click);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("mousedown", click); document.removeEventListener("keydown", escape); };
  }, [open]);

  const selected = options.find(([code]) => code === value);
  const filtered = options.filter(([, label]) => label.toLowerCase().includes(query.trim().toLowerCase()));

  return <div className={styles.picker} ref={container}>
    <button type="button" className={styles.toggle} onClick={() => { setOpen(value => !value); setQuery(""); }} aria-haspopup="listbox" aria-expanded={open} aria-label={ariaLabel}>
      <span>{selected?.[1] || "Any language"}</span><ChevronDown />
    </button>
    {open && <div className={styles.menu} role="listbox" aria-label={ariaLabel}>
      <input autoFocus value={query} onChange={event => setQuery(event.target.value)} placeholder="Type to search…" aria-label="Search languages" />
      <ul>
        {filtered.map(([code, label]) => <li key={code || "any"}>
          <button type="button" className={code === value ? styles.selected : ""} onClick={() => { onChange(code); setOpen(false); }}>{label}</button>
        </li>)}
        {!filtered.length && <li className={styles.empty}>No languages match</li>}
      </ul>
    </div>}
  </div>;
}
