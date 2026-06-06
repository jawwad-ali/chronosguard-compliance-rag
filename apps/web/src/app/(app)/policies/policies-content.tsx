"use client";

import Link from "next/link";
import { ChevronRight, FileText } from "lucide-react";
import { useState } from "react";

import { NewPolicyDialog } from "@/components/policies/new-policy-dialog";
import { EmptyState } from "@/components/brand/empty-state";
import { ErrorState } from "@/components/brand/error-state";
import { PageHeader } from "@/components/brand/page-header";
import { PaginationControls } from "@/components/brand/pagination-controls";
import { Skeleton } from "@/components/ui/skeleton";
import { usePolicies } from "@/lib/api/queries";
import { DEFAULT_PAGE_SIZE } from "@/lib/constants";
import { formatRelative } from "@/lib/format";

export const PoliciesContent = () => {
  const [offset, setOffset] = useState(0);
  const { data, isPending, isError, error, refetch } = usePolicies(offset);

  return (
    <div className="space-y-6">
      <PageHeader
        kicker="Internal documents"
        title="Policies"
        description="Versioned under row-level security. Every body change appends an immutable version — audits stay explainable forever."
        actions={<NewPolicyDialog />}
      />

      {isPending ? (
        <Skeleton className="h-64 rounded-lg" />
      ) : isError ? (
        <ErrorState error={error} onRetry={() => refetch()} />
      ) : data.items.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="No policies stored"
          description="Store a policy once and audit it against any date — versions are kept immutably."
          action={<NewPolicyDialog />}
        />
      ) : (
        <>
          <ol className="divide-y divide-border rounded-lg border border-border bg-card shadow-sheet">
            {data.items.map((policy) => (
              <li key={policy.id} className="group">
                <Link
                  href={`/policies/${policy.id}`}
                  className="flex items-center gap-4 px-4 py-3.5 transition-colors duration-200 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                >
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-secondary">
                    <FileText className="h-4 w-4 text-secondary-foreground" aria-hidden />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-charcoal-400">
                      {policy.title}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      updated {formatRelative(policy.updated_at)}
                    </p>
                  </div>
                  <span className="ledger-label shrink-0 rounded-full bg-muted px-2 py-1">
                    v{policy.current_version_no}
                  </span>
                  <ChevronRight
                    className="h-4 w-4 shrink-0 text-charcoal-800 transition-transform duration-200 group-hover:translate-x-0.5"
                    aria-hidden
                  />
                </Link>
              </li>
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
