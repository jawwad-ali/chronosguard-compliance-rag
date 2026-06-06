import type { Metadata } from "next";

import { RegulatoryContent } from "@/app/(app)/regulatory/regulatory-content";

export const metadata: Metadata = { title: "Regulatory" };

export default function RegulatoryPage() {
  return <RegulatoryContent />;
}
