import { ExternalLink, ScrollText } from "lucide-react";

import { cn } from "@/lib/utils";

interface CitationChipProps {
  citation: string;
  sourceUrl?: string;
  className?: string;
}

/** Gazette reference, typeset like a statutory citation. */
export const CitationChip = ({ citation, sourceUrl, className }: CitationChipProps) => {
  const body = (
    <>
      <ScrollText className="h-3.5 w-3.5 shrink-0 text-charcoal-600" aria-hidden />
      <span className="truncate font-medium">{citation}</span>
      {sourceUrl ? (
        <ExternalLink className="h-3 w-3 shrink-0 opacity-60" aria-hidden />
      ) : null}
    </>
  );

  const classes = cn(
    "inline-flex max-w-full items-center gap-1.5 rounded-md border border-charcoal-500/25",
    "bg-secondary px-2.5 py-1 text-xs text-secondary-foreground",
    className,
  );

  if (sourceUrl) {
    return (
      <a
        href={sourceUrl}
        target="_blank"
        rel="noreferrer noopener"
        className={cn(
          classes,
          "transition-colors duration-200 hover:border-verdigris-400 hover:bg-accent",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        )}
        aria-label={`Open source gazette for ${citation}`}
      >
        {body}
      </a>
    );
  }
  return <span className={classes}>{body}</span>;
};
