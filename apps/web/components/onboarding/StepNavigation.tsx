import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

const names = ["Connect", "Select", "Process"];

export default function StepNavigation({ step, navigate }: { step: number; navigate: (step: number) => void }) {
  return <nav aria-label="Setup progress"><ol className="flex flex-wrap items-center gap-1">{names.map((name, index) => <li key={name} className="flex items-center gap-1">
    {index > 0 && <span aria-hidden="true" className={cn("h-px w-6", index <= step ? "bg-primary/60" : "bg-border-strong")} />}
    <button type="button" aria-current={index === step ? "step" : undefined} disabled={index > step} onClick={() => index <= step && navigate(index)} className={cn("flex h-9 items-center gap-2 px-2.5 text-[13px] font-medium transition-colors disabled:cursor-default", index === step ? "text-foreground" : index < step ? "text-muted-foreground hover:text-foreground" : "text-subtle-foreground")}>
      <span className={cn("grid size-6 place-items-center border text-xs tabular-nums", index === step ? "border-primary bg-primary text-primary-foreground" : index < step ? "border-primary/60 text-primary" : "border-border-strong")} aria-label={index < step ? "Completed" : undefined}>{index < step ? <Check className="size-3.5" /> : index + 1}</span>{name}
    </button>
  </li>)}</ol></nav>;
}
