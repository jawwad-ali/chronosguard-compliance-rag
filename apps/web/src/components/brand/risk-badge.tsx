import { ChevronsUp, ChevronUp, Minus } from "lucide-react";

import type { RiskLevel } from "@/lib/api/types";
import { RISK_META } from "@/lib/constants";
import { cn } from "@/lib/utils";

/** The risk ladder IS the palette: tuscan → sandy → burnt peach. */
const RISK_CLASSES: Record<RiskLevel, string> = {
  HIGH: "bg-peach-900 text-peach-300 border-peach-500/40",
  MEDIUM: "bg-sandy-900 text-sandy-300 border-sandy-500/50",
  LOW: "bg-tuscan-800 text-tuscan-200 border-tuscan-400/40",
};

const RISK_ICONS: Record<RiskLevel, React.ComponentType<{ className?: string }>> = {
  HIGH: ChevronsUp,
  MEDIUM: ChevronUp,
  LOW: Minus,
};

export const RiskBadge = ({
  risk,
  className,
}: {
  risk: RiskLevel;
  className?: string;
}) => {
  const Icon = RISK_ICONS[risk];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5",
        "text-[0.6875rem] font-semibold uppercase tracking-[0.08em]",
        RISK_CLASSES[risk],
        className,
      )}
    >
      <Icon className="h-3 w-3" aria-hidden />
      {RISK_META[risk].label}
    </span>
  );
};
