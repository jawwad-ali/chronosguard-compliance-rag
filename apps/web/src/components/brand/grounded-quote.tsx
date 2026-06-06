import { BadgeCheck } from "lucide-react";

import { cn } from "@/lib/utils";

interface GroundedQuoteProps {
  quote: string;
  className?: string;
}

/**
 * A verbatim span from the gazette, server-verified before it ever reached
 * this screen. The check mark is earned, not decorative.
 */
export const GroundedQuote = ({ quote, className }: GroundedQuoteProps) => (
  <figure
    className={cn(
      "relative rounded-md border-l-4 border-verdigris-400 bg-verdigris-900/35 py-3 pl-4 pr-10",
      className,
    )}
  >
    <blockquote className="text-sm italic leading-relaxed text-charcoal-300">
      “{quote}”
    </blockquote>
    <figcaption className="absolute right-3 top-3" title="Quote verified verbatim against the source text">
      <BadgeCheck className="h-4 w-4 text-verdigris-400" aria-label="Verified verbatim quote" />
    </figcaption>
  </figure>
);
