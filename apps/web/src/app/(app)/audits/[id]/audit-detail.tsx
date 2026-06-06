"use client";

import Link from "next/link";
import { ArrowLeft, FileSearch, Loader2, ShieldCheck } from "lucide-react";

import { CoverageBar } from "@/components/brand/coverage-bar";
import { DocketDate } from "@/components/brand/docket-date";
import { EmptyState } from "@/components/brand/empty-state";
import { ErrorState } from "@/components/brand/error-state";
import { StaleBanner } from "@/components/brand/stale-banner";
import { StatusPill } from "@/components/brand/status-pill";
import { VerdictStamp } from "@/components/brand/verdict-stamp";
import { FindingCard } from "@/components/audits/finding-card";
import { Skeleton } from "@/components/ui/skeleton";
import { useAudit, useFindings } from "@/lib/api/queries";
import type { AuditRunOut } from "@/lib/api/types";
import { RUN_STATUS_META } from "@/lib/constants";
import {
  formatCostUsd,
  formatLegalDate,
  formatRelative,
  formatTokens,
} from "@/lib/format";

const DetailSkeleton = () => (
  <div className="space-y-6">
    <Skeleton className="h-8 w-40" />
    <Skeleton className="h-44 rounded-lg" />
    <Skeleton className="h-24 rounded-lg" />
  </div>
);

const RunMeta = ({ run }: { run: AuditRunOut }) => (
  <dl className="grid grid-cols-2 gap-x-8 gap-y-2 text-xs sm:grid-cols-4">
    {[
      ["Model", run.model ?? "—"],
      ["Tokens", formatTokens(run.total_tokens)],
      ["Cost", formatCostUsd(run.cost_usd)],
      [
        "Finished",
        run.finished_at ? formatRelative(run.finished_at) : "in progress",
      ],
    ].map(([label, value]) => (
      <div key={label} className="ledger-leader">
        <dt className="text-muted-foreground">{label}</dt>
        <dd className="font-medium text-charcoal-400">{value}</dd>
      </div>
    ))}
  </dl>
);

const RunningPanel = () => (
  <div className="flex items-center gap-4 rounded-lg border border-border bg-card px-5 py-6 shadow-sheet">
    <Loader2 className="h-5 w-5 animate-spin text-primary" aria-hidden />
    <div>
      <p className="text-sm font-medium text-charcoal-400">
        Auditing clause by clause…
      </p>
      <p className="text-xs text-muted-foreground">
        Retrieving the law in force, judging each clause, and verifying every
        quote against the source text.
      </p>
    </div>
  </div>
);

export const AuditDetail = ({ runId }: { runId: number }) => {
  const audit = useAudit(runId);
  const terminal = audit.data ? RUN_STATUS_META[audit.data.status].terminal : false;
  const findings = useFindings(runId, terminal);

  if (audit.isPending) return <DetailSkeleton />;
  if (audit.isError) {
    return (
      <div className="space-y-4">
        <BackLink />
        <ErrorState error={audit.error} onRetry={() => audit.refetch()} />
      </div>
    );
  }

  const run = audit.data;

  return (
    <div className="space-y-6">
      <BackLink />

      {/* The docket sheet */}
      <section className="sheet-margin animate-rise rounded-lg border border-border bg-card py-5 pl-10 pr-5 shadow-sheet sm:pl-12 sm:pr-8">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-4">
            <div>
              <p className="ledger-label">Audit №{run.id}</p>
              <h1 className="mt-1 text-2xl font-semibold tracking-tight text-charcoal-400 sm:text-3xl">
                {run.jurisdiction} · {formatLegalDate(run.as_of_date)}
              </h1>
              <p className="mt-1 text-sm text-muted-foreground">
                Verdict rendered against the regulation in force on the anchor
                date — not today&apos;s law.
              </p>
            </div>
            <RunMeta run={run} />
          </div>

          <div className="flex shrink-0 items-center gap-6 lg:flex-col lg:items-end">
            <DocketDate iso={run.as_of_date} />
            {run.verdict ? (
              <VerdictStamp verdict={run.verdict} size="lg" animate />
            ) : (
              <StatusPill status={run.status} />
            )}
          </div>
        </div>

        {run.coverage ? (
          <div className="mt-6 border-t border-border pt-4">
            <p className="ledger-label mb-2">Clause coverage</p>
            <CoverageBar coverage={run.coverage} />
          </div>
        ) : null}
      </section>

      {run.stale ? <StaleBanner /> : null}

      {!terminal ? <RunningPanel /> : null}

      {run.status === "failed" ? (
        <ErrorState
          error={null}
          title={`This run failed${run.error ? ` (${run.error})` : ""}`}
        />
      ) : null}

      {terminal && run.status !== "failed" ? (
        <section className="space-y-4">
          <h2 className="ledger-label">
            Findings{findings.data ? ` (${findings.data.total})` : ""}
          </h2>

          {findings.isPending ? (
            <Skeleton className="h-48 rounded-lg" />
          ) : findings.isError ? (
            <ErrorState error={findings.error} onRetry={() => findings.refetch()} />
          ) : findings.data.items.length === 0 ? (
            run.verdict === "COMPLIANT" ? (
              <EmptyState
                icon={ShieldCheck}
                title="No violations found"
                description="Every evaluated clause held up against the law in force on the anchor date."
              />
            ) : (
              <EmptyState
                icon={FileSearch}
                title="No governing law retrieved"
                description="The corpus contains no confirmed regulation covering these clauses for this jurisdiction and date. That is reported honestly — never as compliance."
              />
            )
          ) : (
            <ol className="space-y-4">
              {findings.data.items.map((finding, index) => (
                <FindingCard key={finding.id} finding={finding} ordinal={index + 1} />
              ))}
            </ol>
          )}
        </section>
      ) : null}
    </div>
  );
};

const BackLink = () => (
  <Link
    href="/audits"
    className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors duration-200 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
  >
    <ArrowLeft className="h-4 w-4" aria-hidden />
    Audit ledger
  </Link>
);
