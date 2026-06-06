"use client";

import { ErrorState } from "@/components/brand/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useMe } from "@/lib/api/queries";
import { formatLegalDate } from "@/lib/format";

export const OrgCard = () => {
  const { data, isPending, isError, error, refetch } = useMe();

  if (isPending) return <Skeleton className="h-32 rounded-lg" />;
  if (isError) return <ErrorState error={error} onRetry={() => refetch()} />;

  return (
    <section className="rounded-lg border border-border bg-card p-5 shadow-sheet">
      <h2 className="ledger-label">Organization</h2>
      <dl className="mt-3 grid grid-cols-1 gap-x-8 gap-y-3 sm:grid-cols-3">
        <div>
          <dt className="text-xs text-muted-foreground">Name</dt>
          <dd className="text-sm font-medium text-charcoal-400">{data.name}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Home jurisdiction</dt>
          <dd className="text-sm font-medium text-charcoal-400">{data.home_jurisdiction}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Registered</dt>
          <dd className="text-sm font-medium text-charcoal-400">
            {formatLegalDate(data.created_at)}
          </dd>
        </div>
      </dl>
    </section>
  );
};
