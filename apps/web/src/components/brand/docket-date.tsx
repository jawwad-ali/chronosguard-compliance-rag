import { format, parseISO } from "date-fns";

import { cn } from "@/lib/utils";

interface DocketDateProps {
  iso: string;
  /** The label above the leaf, e.g. "As of". */
  label?: string;
  className?: string;
}

/**
 * The temporal anchor, displayed as a calendar leaf — because "what law was
 * in force ON THIS DATE" is the entire product. It deserves furniture.
 */
export const DocketDate = ({ iso, label = "As of", className }: DocketDateProps) => {
  const date = parseISO(iso);
  return (
    <div className={cn("inline-flex items-stretch gap-3", className)}>
      <div className="flex w-14 shrink-0 flex-col overflow-hidden rounded-md border border-charcoal-500/25 bg-card shadow-sheet">
        <div className="bg-charcoal-500 px-1 py-0.5 text-center text-[0.5625rem] font-semibold uppercase tracking-[0.2em] text-tuscan-900">
          {format(date, "MMM")}
        </div>
        <div className="py-1 text-center text-xl font-bold leading-none text-charcoal-400">
          {format(date, "d")}
        </div>
        <div className="pb-1 text-center text-[0.625rem] font-medium text-muted-foreground">
          {format(date, "yyyy")}
        </div>
      </div>
      <div className="flex flex-col justify-center">
        <span className="ledger-label">{label}</span>
        <span className="text-sm font-medium text-foreground">
          {format(date, "EEEE")}
        </span>
      </div>
    </div>
  );
};
