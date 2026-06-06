import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { AuditDetail } from "@/app/(app)/audits/[id]/audit-detail";

export const metadata: Metadata = { title: "Audit" };

export default async function AuditDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const runId = Number(id);
  if (!Number.isInteger(runId) || runId <= 0) notFound();

  return <AuditDetail runId={runId} />;
}
