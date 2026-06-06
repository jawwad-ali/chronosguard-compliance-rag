"use client";

import Link from "next/link";
import { ChevronRight, Landmark, ScrollText } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/brand/empty-state";
import { ErrorState } from "@/components/brand/error-state";
import { PaginationControls } from "@/components/brand/pagination-controls";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useDocuments } from "@/lib/api/queries";
import { DEFAULT_PAGE_SIZE } from "@/lib/constants";
import { formatLegalDate } from "@/lib/format";

export const DocumentBrowser = () => {
  const [offset, setOffset] = useState(0);
  const [issuingBody, setIssuingBody] = useState("");
  const { data, isPending, isError, error, refetch } = useDocuments(offset, {
    issuing_body: issuingBody || undefined,
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-2">
          <Label htmlFor="filter-body">Issuing body</Label>
          <Input
            id="filter-body"
            value={issuingBody}
            onChange={(event) => {
              setIssuingBody(event.target.value.toUpperCase());
              setOffset(0);
            }}
            placeholder="SECP"
            className="h-10 w-36 bg-card uppercase"
          />
        </div>
      </div>

      {isPending ? (
        <Skeleton className="h-64 rounded-lg" />
      ) : isError ? (
        <ErrorState error={error} onRetry={() => refetch()} />
      ) : data.items.length === 0 ? (
        <EmptyState
          icon={ScrollText}
          title="No confirmed documents"
          description="The corpus has no confirmed documents matching this filter — quarantined documents never appear here."
        />
      ) : (
        <>
          <ol className="divide-y divide-border rounded-lg border border-border bg-card shadow-sheet">
            {data.items.map((document) => (
              <li key={document.id} className="group">
                <Link
                  href={`/regulatory/${document.id}`}
                  className="flex items-center gap-4 px-4 py-3.5 transition-colors duration-200 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                >
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-secondary">
                    <Landmark className="h-4 w-4 text-secondary-foreground" aria-hidden />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-charcoal-400">
                      {document.title}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {document.issuing_body} · {document.document_type} ·{" "}
                      {document.jurisdiction} · published{" "}
                      {formatLegalDate(document.published_date)}
                    </p>
                  </div>
                  {document.version > 1 ? (
                    <span className="ledger-label shrink-0 rounded-full bg-muted px-2 py-1">
                      v{document.version}
                    </span>
                  ) : null}
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
