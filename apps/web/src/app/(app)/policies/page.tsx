import type { Metadata } from "next";

import { PoliciesContent } from "@/app/(app)/policies/policies-content";

export const metadata: Metadata = { title: "Policies" };

export default function PoliciesPage() {
  return <PoliciesContent />;
}
