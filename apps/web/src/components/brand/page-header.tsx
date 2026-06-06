import { cn } from "@/lib/utils";

interface PageHeaderProps {
  /** Editorial kicker above the title, e.g. "Audit ledger". */
  kicker: string;
  title: React.ReactNode;
  description?: string;
  actions?: React.ReactNode;
  className?: string;
}

/** Editorial page masthead: kicker, display title, hairline rule. */
export const PageHeader = ({
  kicker,
  title,
  description,
  actions,
  className,
}: PageHeaderProps) => (
  <header className={cn("animate-rise space-y-3 border-b border-border pb-5", className)}>
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="space-y-1">
        <p className="ledger-label">{kicker}</p>
        <h1 className="text-2xl font-semibold tracking-tight text-charcoal-400 sm:text-3xl">
          {title}
        </h1>
        {description ? (
          <p className="max-w-2xl text-sm text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  </header>
);
