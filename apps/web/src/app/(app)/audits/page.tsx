import type { Metadata } from "next";

import { AuditsContent } from "@/app/(app)/audits/audits-content";

export const metadata: Metadata = { title: "Audits" };

export default function AuditsPage() {
  return <AuditsContent />;
}
