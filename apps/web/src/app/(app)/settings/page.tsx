import type { Metadata } from "next";
import { Unplug } from "lucide-react";

import { disconnectAction } from "@/app/connect/actions";
import { PageHeader } from "@/components/brand/page-header";
import { OrgCard } from "@/app/(app)/settings/org-card";
import { Button } from "@/components/ui/button";

export const metadata: Metadata = { title: "Settings" };

export default function SettingsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        kicker="Configuration"
        title="Settings"
        description="Connection and organization details for this ledger session."
      />

      <OrgCard />

      <section className="rounded-lg border border-border bg-card p-5 shadow-sheet">
        <h2 className="ledger-label">Session</h2>
        <p className="mt-2 max-w-xl text-sm text-muted-foreground">
          Your organization API key is held in an httpOnly cookie on this device.
          Disconnecting removes it; the key itself stays valid until an operator
          revokes it.
        </p>
        <form action={disconnectAction} className="mt-4">
          <Button type="submit" variant="outline" className="gap-2">
            <Unplug className="h-4 w-4" aria-hidden />
            Disconnect this device
          </Button>
        </form>
      </section>
    </div>
  );
}
