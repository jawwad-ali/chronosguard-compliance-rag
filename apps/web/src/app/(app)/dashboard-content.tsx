"use client";

import Link from "next/link";
import { ArrowRight, FileText, Stamp } from "lucide-react";

import { EmptyState } from "@/components/brand/empty-state";
import { ErrorState } from "@/components/brand/error-state";
import { MetricCard } from "@/components/brand/metric-card";
import { AuditRow } from "@/components/audits/audit-row";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAudits, usePolicies } from "@/lib/api/queries";

const DashboardSkeleton = () => (
  <div className="space-y-6">
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      {[0, 1, 2].map((i) => (
        <Skeleton key={i} className="h-28 rounded-lg" />
      ))}
    </div>
    <Skeleton className="h-64 rounded-lg" />
  </div>
);

export const DashboardContent = () => {
  const audits = useAudits(0);
  const policies = usePolicies(0);

  if (audits.isPending || policies.isPending) return <DashboardSkeleton />;
  if (audits.isError) {
    return <ErrorState error={audits.error} onRetry={() => audits.refetch()} />;
  }

  const runs = audits.data.items;
  const violations = runs.filter((run) => run.verdict === "VIOLATIONS_FOUND").length;
  const staleCount = runs.filter((run) => run.stale).length;

  return (
    <div className="space-y-8">
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <MetricCard
          label="Audit runs"
          value={audits.data.total}
          hint="All time, this organization"
          icon={<Stamp className="h-4 w-4" aria-hidden />}
        />
        <MetricCard
          label="With violations"
          value={<span className={violations > 0 ? "text-peach-400" : undefined}>{violations}</span>}
          hint="Among the most recent runs"
        />
        <MetricCard
          label="Stored policies"
          value={policies.isSuccess ? policies.data.total : "—"}
          hint="Versioned under row-level security"
          icon={<FileText className="h-4 w-4" aria-hidden />}
        />
      </section>

      {staleCount > 0 ? (
        <p className="rounded-md border border-sandy-500/50 bg-sandy-900 px-4 py-2.5 text-sm text-sandy-200">
          {staleCount} recent verdict{staleCount > 1 ? "s" : ""} may be affected by
          retroactive amendments — review them in the audit ledger.
        </p>
      ) : null}

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="ledger-label">Recent audits</h2>
          <Button asChild variant="ghost" size="sm" className="gap-1 text-primary">
            <Link href="/audits">
              View ledger <ArrowRight className="h-3.5 w-3.5" aria-hidden />
            </Link>
          </Button>
        </div>

        {runs.length === 0 ? (
          <EmptyState
            icon={Stamp}
            title="No audits yet"
            description="Run your first audit to see how your policies hold up against the law in force."
            action={
              <Button asChild>
                <Link href="/audits">Run an audit</Link>
              </Button>
            }
          />
        ) : (
          <ol className="divide-y divide-border rounded-lg border border-border bg-card shadow-sheet">
            {runs.slice(0, 6).map((run) => (
              <AuditRow key={run.id} run={run} />
            ))}
          </ol>
        )}
      </section>
    </div>
  );
};
