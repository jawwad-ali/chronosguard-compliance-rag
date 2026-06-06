import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { DocumentDetailView } from "@/app/(app)/regulatory/[id]/document-detail";

export const metadata: Metadata = { title: "Document" };

export default async function RegulatoryDocumentPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const documentId = Number(id);
  if (!Number.isInteger(documentId) || documentId <= 0) notFound();

  return <DocumentDetailView documentId={documentId} />;
}
