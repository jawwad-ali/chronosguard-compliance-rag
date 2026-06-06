import { cn } from "@/lib/utils";

interface MetricCardProps {
  label: string;
  value: React.ReactNode;
  hint?: string;
  icon?: React.ReactNode;
  className?: string;
}

/** Ledger stat: uppercase label, oversized figure, dotted-leader hint. */
export const MetricCard = ({ label, value, hint, icon, className }: MetricCardProps) => (
  <div
    className={cn(
      "rounded-lg border border-border bg-card p-4 shadow-sheet",
      "transition-all duration-200 hover:-translate-y-0.5 hover:shadow-sheet-hover",
      className,
    )}
  >
    <div className="flex items-center justify-between gap-2">
      <span className="ledger-label">{label}</span>
      {icon ? <span className="text-charcoal-700">{icon}</span> : null}
    </div>
    <div className="mt-2 text-3xl font-semibold tracking-tight text-charcoal-400">
      {value}
    </div>
    {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
  </div>
);
