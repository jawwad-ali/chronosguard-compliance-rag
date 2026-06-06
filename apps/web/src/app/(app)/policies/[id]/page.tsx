import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { PolicyDetail } from "@/app/(app)/policies/[id]/policy-detail";

export const metadata: Metadata = { title: "Policy" };

export default async function PolicyDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const policyId = Number(id);
  if (!Number.isInteger(policyId) || policyId <= 0) notFound();

  return <PolicyDetail policyId={policyId} />;
}
