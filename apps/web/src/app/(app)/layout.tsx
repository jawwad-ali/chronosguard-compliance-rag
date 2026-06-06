import Link from "next/link";

import { Wordmark } from "@/components/brand/wordmark";
import { MobileNav } from "@/components/shell/mobile-nav";
import { OrgBadge } from "@/components/shell/org-badge";
import { SidebarNav } from "@/components/shell/sidebar-nav";
import { requireApiKey } from "@/lib/server/session";

export default async function AppLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  await requireApiKey(); // no session → /connect

  return (
    <div className="relative z-10 flex min-h-screen">
      {/* Desktop sidebar — the ledger's spine */}
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col gap-6 border-r border-border bg-card/70 p-4 backdrop-blur-sm lg:flex">
        <Link
          href="/"
          className="rounded-md px-1 py-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          <Wordmark />
        </Link>
        <SidebarNav />
        <div className="mt-auto">
          <OrgBadge />
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Mobile topbar */}
        <header className="sticky top-0 z-20 flex items-center justify-between gap-3 border-b border-border bg-background/90 px-4 py-3 backdrop-blur-sm lg:hidden">
          <Link href="/">
            <Wordmark />
          </Link>
          <MobileNav />
        </header>

        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6 sm:py-8 lg:px-8">
          {children}
        </main>
      </div>
    </div>
  );
}
