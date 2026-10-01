"use client";

import { useId, type ReactNode } from "react";
import { Switch } from "../ui/switch";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "../ui/select";
import { SettingRow } from "./SettingRow";

// Same scale as PaneSection: 14px title, 12px hint. Rows below supply their own dividers.
export function SectionHeading({ title, description, count, id }: { title: string; description?: string; count?: number; id?: string }) {
  return <div id={id} className="flex items-end justify-between gap-3 border-b border-border pb-3">
    <div className="min-w-0"><h2 className="text-sm font-semibold">{title}</h2>{description && <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{description}</p>}</div>
    {count !== undefined && <span className="text-xs tabular-nums text-muted-foreground" aria-label={`${count} entries`}>{count}</span>}
  </div>;
}
export function Toggle({ label, checked, onChange, disabled, description }: { label: string; checked: boolean; onChange: (next: boolean) => void; disabled?: boolean; description?: string }) {
  const id = useId();
  return <SettingRow label={label} htmlFor={id} description={description}><Switch id={id} checked={checked} onCheckedChange={onChange} disabled={disabled} /></SettingRow>;
}
export function Choice({ value, onChange, children, id, disabled, "aria-label": ariaLabel }: { value: string; onChange: (value: string) => void; children: ReactNode; id?: string; disabled?: boolean; "aria-label"?: string }) {
  return <Select value={value} onValueChange={onChange} disabled={disabled}><SelectTrigger id={id} aria-label={ariaLabel} className="w-full min-w-0"><SelectValue /></SelectTrigger><SelectContent>{children}</SelectContent></Select>;
}
export const ChoiceItem = SelectItem;
