"use client";

import Link from "next/link";
import { ArrowLeft, ExternalLink } from "lucide-react";

import { ChunkValidity } from "@/components/regulatory/chunk-validity";
import { ErrorState } from "@/components/brand/error-state";
import { PageHeader } from "@/components/brand/page-header";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useChunks, useDocument } from "@/lib/api/queries";
import { formatLegalDate } from "@/lib/format";

export const DocumentDetailView = ({ documentId }: { documentId: number }) => {
  const document = useDocument(documentId);
  const chunks = useChunks(documentId);

  if (document.isPending) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-40 rounded-lg" />
        <Skeleton className="h-64 rounded-lg" />
      </div>
    );
  }
  if (document.isError) {
    return (
      <div className="space-y-4">
        <BackLink />
        <ErrorState error={document.error} onRetry={() => document.refetch()} />
      </div>
    );
  }

  const doc = document.data;

  return (
    <div className="space-y-6">
      <BackLink />

      <PageHeader
        kicker={`${doc.issuing_body} · ${doc.document_type} · ${doc.jurisdiction}${doc.version > 1 ? ` · v${doc.version}` : ""}`}
        title={doc.title}
        description={`Published ${formatLegalDate(doc.published_date)} · ${doc.chunk_count} section${doc.chunk_count === 1 ? "" : "s"} in the corpus`}
        actions={
          <Button asChild variant="outline" className="gap-2">
            <a href={doc.source_url} target="_blank" rel="noreferrer noopener">
              <ExternalLink className="h-4 w-4" aria-hidden />
              Source gazette
            </a>
          </Button>
        }
      />

      <section className="space-y-3">
        <h2 className="ledger-label">Sections</h2>
        {chunks.isPending ? (
          <Skeleton className="h-64 rounded-lg" />
        ) : chunks.isError ? (
          <ErrorState error={chunks.error} onRetry={() => chunks.refetch()} />
        ) : (
          <ol className="space-y-3">
            {chunks.data.items.map((chunk) => (
              <li
                key={chunk.id}
                className="sheet-margin rounded-lg border border-border bg-card py-4 pl-10 pr-5 shadow-sheet sm:pl-12"
              >
                <div className="mb-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <span className="text-sm font-semibold text-charcoal-400">
                    {chunk.legal_citation}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {chunk.heading_path}
                  </span>
                </div>
                <p className="whitespace-pre-line text-sm leading-relaxed text-charcoal-400">
                  {chunk.content}
                </p>
                <div className="mt-3 border-t border-border pt-2">
                  <ChunkValidity
                    effective={chunk.effective_date}
                    expiration={chunk.expiration_date}
                    source={chunk.effective_date_source}
                  />
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
};

const BackLink = () => (
  <Link
    href="/regulatory"
    className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors duration-200 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
  >
    <ArrowLeft className="h-4 w-4" aria-hidden />
    Regulatory explorer
  </Link>
);
