"use client";

import { useState, type KeyboardEvent } from "react";
import { X } from "lucide-react";
import styles from "./TagInput.module.css";

export type Tag = { label: string; negative: boolean };

export default function TagInput({ label, placeholder, tags, onChange }: {
  label: string;
  placeholder: string;
  tags: Tag[];
  onChange: (tags: Tag[]) => void;
}) {
  const [draft, setDraft] = useState("");

  function commit() {
    const value = draft.trim().replace(/^[-+]+/, "").trim();
    if (!value) { setDraft(""); return; }
    const negative = draft.trim().startsWith("-");
    if (tags.some(tag => tag.label.toLowerCase() === value.toLowerCase() && tag.negative === negative)) { setDraft(""); return; }
    onChange([...tags, { label: value, negative }]);
    setDraft("");
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") { event.preventDefault(); commit(); }
    else if (event.key === "Backspace" && !draft && tags.length) { onChange(tags.slice(0, -1)); }
  }

  function remove(index: number) { onChange(tags.filter((_, position) => position !== index)); }

  return <label>
    <span>{label}</span>
    <div className={styles.field}>
      {tags.map((tag, index) => <span key={`${tag.label}-${index}`} className={tag.negative ? styles.negative : styles.positive}>{tag.negative ? "−" : "+"}{tag.label}<button type="button" onClick={() => remove(index)} aria-label={`Remove ${tag.label}`}><X /></button></span>)}
      <input
        value={draft}
        onChange={event => setDraft(event.target.value)}
        onKeyDown={onKeyDown}
        onBlur={commit}
        placeholder={tags.length ? "" : placeholder}
        aria-label={label}
      />
    </div>
  </label>;
}
