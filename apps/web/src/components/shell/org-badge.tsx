"use client";

import { Building2 } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { useMe } from "@/lib/api/queries";

/** Footer of the sidebar: who is signed in (org-level identity). */
export const OrgBadge = () => {
  const { data, isPending, isError } = useMe();

  if (isPending) {
    return (
      <div className="flex items-center gap-2.5 px-3 py-2">
        <Skeleton className="h-8 w-8 rounded-md" />
        <div className="space-y-1.5">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-2.5 w-14" />
        </div>
      </div>
    );
  }
  if (isError || !data) return null;

  return (
    <div className="flex items-center gap-2.5 rounded-md bg-muted px-3 py-2">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-charcoal-500 text-tuscan-900">
        <Building2 className="h-4 w-4" aria-hidden />
      </span>
      <div className="min-w-0 leading-tight">
        <p className="truncate text-sm font-medium text-charcoal-400">{data.name}</p>
        <p className="ledger-label text-[0.5625rem]">{data.home_jurisdiction}</p>
      </div>
    </div>
  );
};
