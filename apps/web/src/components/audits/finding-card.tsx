import Link from "next/link";
import { Eye, Wrench } from "lucide-react";

import { CitationChip } from "@/components/brand/citation-chip";
import { GroundedQuote } from "@/components/brand/grounded-quote";
import { RiskBadge } from "@/components/brand/risk-badge";
import type { FindingOut } from "@/lib/api/types";
import { formatConfidence } from "@/lib/format";

interface FindingCardProps {
  finding: FindingOut;
  ordinal: number;
}

/**
 * One ledger entry: the spec's split view — your policy on the left, the law
 * in force on the right, with a server-verified verbatim quote.
 */
export const FindingCard = ({ finding, ordinal }: FindingCardProps) => (
  <li className="animate-rise overflow-hidden rounded-lg border border-border bg-card shadow-sheet">
    {/* Entry header */}
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border bg-muted/60 px-5 py-3">
      <span className="ledger-label text-charcoal-500">Finding №{ordinal}</span>
      <RiskBadge risk={finding.risk_level} />
      {finding.needs_review ? (
        <span className="inline-flex items-center gap-1 rounded-full border border-tuscan-400/50 bg-tuscan-800 px-2 py-0.5 text-[0.6875rem] font-semibold uppercase tracking-[0.08em] text-tuscan-200">
          <Eye className="h-3 w-3" aria-hidden />
          Needs review
        </span>
      ) : null}
      <span className="ml-auto text-xs text-muted-foreground">
        Clause {finding.clause_index + 1} · confidence {formatConfidence(finding.confidence)}
      </span>
    </div>

    {/* The split view */}
    <div className="grid grid-cols-1 gap-5 px-5 py-5 md:grid-cols-2">
      <div className="space-y-2">
        <p className="ledger-label text-peach-300">Your policy says</p>
        <blockquote className="rounded-md border-l-4 border-peach-500 bg-peach-900/35 py-3 pl-4 pr-4 text-sm leading-relaxed text-charcoal-300">
          {finding.offending_policy_text}
        </blockquote>
      </div>
      <div className="space-y-2">
        <p className="ledger-label text-verdigris-300">The law in force</p>
        <GroundedQuote quote={finding.grounding_quote} />
      </div>
    </div>

    {/* Reasoning + remedy */}
    <div className="space-y-4 px-5 pb-5">
      <p className="text-sm leading-relaxed text-charcoal-400">{finding.rationale}</p>

      <div className="flex items-start gap-3 rounded-md bg-accent px-4 py-3">
        <Wrench className="mt-0.5 h-4 w-4 shrink-0 text-accent-foreground" aria-hidden />
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.08em] text-accent-foreground">
            Suggested fix
          </p>
          <p className="mt-0.5 text-sm text-charcoal-400">{finding.suggested_fix}</p>
        </div>
      </div>
    </div>

    {/* Provenance footer */}
    <div className="flex flex-wrap items-center gap-3 border-t border-border bg-muted/40 px-5 py-3">
      <CitationChip citation={finding.citation} sourceUrl={finding.source_url} />
      {finding.source_document_id ? (
        <Link
          href={`/regulatory/${finding.source_document_id}`}
          className="text-xs font-medium text-primary underline-offset-4 transition-colors duration-200 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          View in corpus →
        </Link>
      ) : null}
      <span className="ml-auto text-[0.6875rem] text-muted-foreground">
        Quote verified server-side against the source text
      </span>
    </div>
  </li>
);
