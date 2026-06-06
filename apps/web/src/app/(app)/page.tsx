import type { Metadata } from "next";

import { DashboardContent } from "@/app/(app)/dashboard-content";
import { PageHeader } from "@/components/brand/page-header";

export const metadata: Metadata = { title: "Dashboard" };

export default function DashboardPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        kicker="The ledger"
        title="Compliance at a glance"
        description="Recent audit activity for your organization, anchored to the dates that matter."
      />
      <DashboardContent />
    </div>
  );
}
