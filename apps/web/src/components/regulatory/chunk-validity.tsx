import { ArrowRight, CalendarCheck2, CalendarOff } from "lucide-react";

import { formatLegalDate } from "@/lib/format";
import { cn } from "@/lib/utils";

interface ChunkValidityProps {
  effective: string;
  expiration: string | null;
  source?: string;
  className?: string;
}

/** The half-open validity interval, rendered as a timeline strip. */
export const ChunkValidity = ({
  effective,
  expiration,
  source,
  className,
}: ChunkValidityProps) => (
  <p className={cn("flex flex-wrap items-center gap-x-2 gap-y-1 text-xs", className)}>
    <span className="inline-flex items-center gap-1 font-medium text-verdigris-300">
      <CalendarCheck2 className="h-3.5 w-3.5" aria-hidden />
      {formatLegalDate(effective)}
    </span>
    <ArrowRight className="h-3 w-3 text-muted-foreground" aria-hidden />
    {expiration ? (
      <span className="inline-flex items-center gap-1 font-medium text-peach-300">
        <CalendarOff className="h-3.5 w-3.5" aria-hidden />
        {formatLegalDate(expiration)}
      </span>
    ) : (
      <span className="font-medium text-muted-foreground">open-ended</span>
    )}
    {source === "defaulted_to_published" ? (
      <span
        className="rounded-full bg-tuscan-800 px-1.5 py-0.5 text-[0.625rem] font-semibold uppercase tracking-[0.08em] text-tuscan-200"
        title="No explicit commencement clause was found; the publication date anchors this rule."
      >
        Defaulted to published
      </span>
    ) : null}
  </p>
);
