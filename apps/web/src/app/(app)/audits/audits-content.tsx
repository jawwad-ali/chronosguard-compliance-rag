"use client";

import { Stamp } from "lucide-react";
import { useState } from "react";

import { AuditRow } from "@/components/audits/audit-row";
import { NewAuditDialog } from "@/components/audits/new-audit-dialog";
import { EmptyState } from "@/components/brand/empty-state";
import { ErrorState } from "@/components/brand/error-state";
import { PageHeader } from "@/components/brand/page-header";
import { PaginationControls } from "@/components/brand/pagination-controls";
import { Skeleton } from "@/components/ui/skeleton";
import { useAudits } from "@/lib/api/queries";
import { DEFAULT_PAGE_SIZE } from "@/lib/constants";

const ListSkeleton = () => (
  <div className="space-y-px overflow-hidden rounded-lg border border-border">
    {[0, 1, 2, 3, 4].map((i) => (
      <Skeleton key={i} className="h-16 rounded-none" />
    ))}
  </div>
);

export const AuditsContent = () => {
  const [offset, setOffset] = useState(0);
  const { data, isPending, isError, error, refetch } = useAudits(offset);

  return (
    <div className="space-y-6">
      <PageHeader
        kicker="Audit ledger"
        title="Audits"
        description="Every run is anchored to an as-of date and snapshots exactly what it reasoned over."
        actions={<NewAuditDialog />}
      />

      {isPending ? (
        <ListSkeleton />
      ) : isError ? (
        <ErrorState error={error} onRetry={() => refetch()} />
      ) : data.items.length === 0 ? (
        <EmptyState
          icon={Stamp}
          title="The ledger is empty"
          description="Audit a stored policy or paste policy text directly — the verdict comes back stamped, cited, and grounded."
          action={<NewAuditDialog />}
        />
      ) : (
        <>
          <ol className="divide-y divide-border rounded-lg border border-border bg-card shadow-sheet">
            {data.items.map((run) => (
              <AuditRow key={run.id} run={run} />
            ))}
          </ol>
          <PaginationControls
            total={data.total}
            offset={offset}
            limit={DEFAULT_PAGE_SIZE}
            onOffsetChange={setOffset}
          />
        </>
      )}
    </div>
  );
};
