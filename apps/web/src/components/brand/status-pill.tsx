import type { RunStatus } from "@/lib/api/types";
import { RUN_STATUS_META } from "@/lib/constants";
import { cn } from "@/lib/utils";

const STATUS_CLASSES: Record<RunStatus, string> = {
  queued: "bg-muted text-muted-foreground",
  running: "bg-accent text-accent-foreground",
  succeeded: "bg-verdigris-900 text-verdigris-300",
  partial: "bg-sandy-900 text-sandy-300",
  failed: "bg-peach-900 text-peach-300",
};

export const StatusPill = ({
  status,
  className,
}: {
  status: RunStatus;
  className?: string;
}) => {
  const live = !RUN_STATUS_META[status].terminal;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5",
        "text-xs font-medium",
        STATUS_CLASSES[status],
        className,
      )}
    >
      {live && (
        <span className="relative flex h-1.5 w-1.5" aria-hidden>
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-60" />
          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-current" />
        </span>
      )}
      {RUN_STATUS_META[status].label}
    </span>
  );
};
