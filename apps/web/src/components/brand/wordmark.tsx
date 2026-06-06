import { cn } from "@/lib/utils";

interface WordmarkProps {
  size?: "sm" | "lg";
  /** Invert for dark (charcoal) surfaces. */
  inverted?: boolean;
  className?: string;
}

/** The masthead: a stamped monogram seal + the ledger title. */
export const Wordmark = ({ size = "sm", inverted = false, className }: WordmarkProps) => (
  <span className={cn("inline-flex items-center gap-2.5", className)}>
    <span
      aria-hidden
      className={cn(
        "flex shrink-0 -rotate-3 items-center justify-center rounded-sm border-2 font-bold",
        size === "lg" ? "h-11 w-11 text-lg" : "h-8 w-8 text-xs",
        inverted
          ? "border-verdigris-600 text-verdigris-700"
          : "border-verdigris-400 text-verdigris-300",
      )}
    >
      <span
        className={cn(
          "flex h-full w-full items-center justify-center rounded-[2px] border border-current/50",
          "tracking-tight",
        )}
      >
        CG
      </span>
    </span>
    <span className="flex flex-col leading-none">
      <span
        className={cn(
          "font-semibold tracking-tight",
          size === "lg" ? "text-xl" : "text-sm",
          inverted ? "text-tuscan-900" : "text-charcoal-400",
        )}
      >
        ChronosGuard
      </span>
      <span
        className={cn(
          "ledger-label mt-0.5",
          size === "lg" ? "text-[0.625rem]" : "text-[0.5625rem]",
          inverted && "text-charcoal-800",
        )}
      >
        Temporal Compliance Ledger
      </span>
    </span>
  </span>
);
