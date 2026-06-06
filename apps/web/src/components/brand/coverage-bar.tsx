import type { Coverage } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const SEGMENTS: {
  key: keyof Coverage;
  label: string;
  className: string;
}[] = [
  { key: "violation", label: "Violations", className: "bg-peach-500" },
  { key: "compliant", label: "Compliant", className: "bg-verdigris-500" },
  { key: "insufficient_evidence", label: "Insufficient", className: "bg-tuscan-500" },
  { key: "error", label: "Errored", className: "bg-charcoal-700" },
];

/** Clause coverage as a segmented rule + legend — the run at a glance. */
export const CoverageBar = ({
  coverage,
  className,
}: {
  coverage: Coverage;
  className?: string;
}) => {
  const total = SEGMENTS.reduce((sum, segment) => sum + coverage[segment.key], 0);
  if (total === 0) return null;

  return (
    <div className={cn("space-y-2", className)}>
      <div
        className="flex h-2.5 w-full overflow-hidden rounded-full border border-charcoal-500/15"
        role="img"
        aria-label={SEGMENTS.map((s) => `${coverage[s.key]} ${s.label.toLowerCase()}`).join(", ")}
      >
        {SEGMENTS.filter((segment) => coverage[segment.key] > 0).map((segment) => (
          <span
            key={segment.key}
            className={cn("h-full transition-all duration-500", segment.className)}
            style={{ width: `${(coverage[segment.key] / total) * 100}%` }}
          />
        ))}
      </div>
      <dl className="flex flex-wrap gap-x-4 gap-y-1">
        {SEGMENTS.map((segment) => (
          <div key={segment.key} className="flex items-center gap-1.5 text-xs">
            <span className={cn("h-2 w-2 rounded-full", segment.className)} aria-hidden />
            <dt className="text-muted-foreground">{segment.label}</dt>
            <dd className="font-semibold text-charcoal-400">{coverage[segment.key]}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
};
