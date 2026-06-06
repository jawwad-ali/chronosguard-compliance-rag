import {
  FileText,
  LayoutGrid,
  type LucideIcon,
  ScrollText,
  Settings,
  Stamp,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Highlight on nested routes too (e.g. /audits/42). */
  matchPrefix?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Dashboard", icon: LayoutGrid },
  { href: "/audits", label: "Audits", icon: Stamp, matchPrefix: true },
  { href: "/policies", label: "Policies", icon: FileText, matchPrefix: true },
  { href: "/regulatory", label: "Regulatory", icon: ScrollText, matchPrefix: true },
  { href: "/settings", label: "Settings", icon: Settings },
];
