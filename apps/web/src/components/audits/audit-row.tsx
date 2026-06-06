import Link from "next/link";
import { ChevronRight, History } from "lucide-react";

import { StatusPill } from "@/components/brand/status-pill";
import { VerdictStamp } from "@/components/brand/verdict-stamp";
import type { AuditRunOut } from "@/lib/api/types";
import { formatLegalDate, formatRelative } from "@/lib/format";

/** One ledger line: docket number, temporal anchor, status, verdict. */
export const AuditRow = ({ run }: { run: AuditRunOut }) => (
  <li className="group">
    <Link
      href={`/audits/${run.id}`}
      className="flex items-center gap-4 px-4 py-3 transition-colors duration-200 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
    >
      <span className="ledger-label w-14 shrink-0 text-charcoal-600">
        №{run.id}
      </span>

      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-charcoal-400">
          {run.jurisdiction} · as of {formatLegalDate(run.as_of_date)}
          {run.stale ? (
            <History
              className="ml-1.5 inline h-3.5 w-3.5 text-sandy-400"
              aria-label="Possibly affected by a retroactive amendment"
            />
          ) : null}
        </p>
        <p className="text-xs text-muted-foreground">
          started {formatRelative(run.created_at)}
        </p>
      </div>

      <div className="hidden shrink-0 sm:block">
        {run.verdict ? (
          <VerdictStamp verdict={run.verdict} />
        ) : (
          <StatusPill status={run.status} />
        )}
      </div>
      <div className="shrink-0 sm:hidden">
        <StatusPill status={run.status} />
      </div>

      <ChevronRight
        className="h-4 w-4 shrink-0 text-charcoal-800 transition-transform duration-200 group-hover:translate-x-0.5"
        aria-hidden
      />
    </Link>
  </li>
);
