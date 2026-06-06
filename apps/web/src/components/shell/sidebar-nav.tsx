"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { NAV_ITEMS } from "@/components/shell/nav-items";
import { cn } from "@/lib/utils";

const isActive = (pathname: string, href: string, matchPrefix?: boolean): boolean =>
  matchPrefix ? pathname === href || pathname.startsWith(`${href}/`) : pathname === href;

export const SidebarNav = ({ onNavigate }: { onNavigate?: () => void }) => {
  const pathname = usePathname();

  return (
    <nav aria-label="Primary" className="flex flex-col gap-1">
      {NAV_ITEMS.map((item) => {
        const active = isActive(pathname, item.href, item.matchPrefix);
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn(
              "group relative flex h-11 items-center gap-3 rounded-md px-3 text-sm font-medium",
              "transition-all duration-200",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
              active
                ? "bg-accent text-accent-foreground"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            {/* The margin rule — active entries get the ledger's red line */}
            <span
              aria-hidden
              className={cn(
                "absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-full transition-all duration-200",
                active ? "bg-peach-500" : "bg-transparent group-hover:bg-charcoal-800",
              )}
            />
            <item.icon className="h-4 w-4 shrink-0" aria-hidden />
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
};
