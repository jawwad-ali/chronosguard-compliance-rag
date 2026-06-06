import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: React.ReactNode;
  className?: string;
}

export const EmptyState = ({
  icon: Icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) => (
  <div
    className={cn(
      "flex flex-col items-center justify-center gap-3 rounded-lg",
      "border border-dashed border-charcoal-500/25 bg-card/60 px-6 py-14 text-center",
      className,
    )}
  >
    <span className="flex h-12 w-12 items-center justify-center rounded-full bg-accent">
      <Icon className="h-6 w-6 text-accent-foreground" aria-hidden />
    </span>
    <div className="space-y-1">
      <h3 className="text-base font-semibold text-charcoal-400">{title}</h3>
      <p className="mx-auto max-w-sm text-sm text-muted-foreground">{description}</p>
    </div>
    {action}
  </div>
);
