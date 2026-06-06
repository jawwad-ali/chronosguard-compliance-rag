import type { Verdict } from "@/lib/api/types";
import { VERDICT_META } from "@/lib/constants";
import { cn } from "@/lib/utils";

const TONE_CLASSES: Record<string, string> = {
  compliant: "border-verdigris-400 text-verdigris-300 bg-verdigris-900/40",
  violation: "border-peach-400 text-peach-300 bg-peach-900/45",
  insufficient: "border-tuscan-300 text-tuscan-200 bg-tuscan-800/50",
};

interface VerdictStampProps {
  verdict: Verdict;
  size?: "sm" | "lg";
  className?: string;
  /** Disable the slam-down entrance (e.g. inside table rows). */
  animate?: boolean;
}

/**
 * The rubber stamp — ChronosGuard's signature mark. A double-ruled, slightly
 * rotated, letterspaced seal pressed onto the paper, exactly like a verdict
 * stamped onto a legal docket.
 */
export const VerdictStamp = ({
  verdict,
  size = "sm",
  className,
  animate = false,
}: VerdictStampProps) => {
  const meta = VERDICT_META[verdict];
  return (
    <span
      role="status"
      aria-label={`Verdict: ${meta.label}`}
      style={{ "--stamp-rotate": size === "lg" ? "-3deg" : "-1.5deg" } as React.CSSProperties}
      className={cn(
        "inline-block select-none rounded-sm border-2 p-0.5",
        size === "lg" ? "rotate-[-3deg]" : "rotate-[-1.5deg]",
        animate && "animate-stamp",
        TONE_CLASSES[meta.tone],
        className,
      )}
    >
      <span
        className={cn(
          "block rounded-[2px] border font-semibold uppercase",
          "border-current/60",
          size === "lg"
            ? "px-4 py-1.5 text-base tracking-[0.22em]"
            : "px-2 py-0.5 text-[0.625rem] tracking-[0.18em]",
        )}
      >
        {meta.label}
      </span>
    </span>
  );
};
