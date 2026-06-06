"use client";

import { Menu } from "lucide-react";
import { useState } from "react";

import { OrgBadge } from "@/components/shell/org-badge";
import { SidebarNav } from "@/components/shell/sidebar-nav";
import { Wordmark } from "@/components/brand/wordmark";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";

export const MobileNav = () => {
  const [open, setOpen] = useState(false);

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button variant="outline" size="icon" className="h-11 w-11 lg:hidden" aria-label="Open navigation">
          <Menu className="h-5 w-5" aria-hidden />
        </Button>
      </SheetTrigger>
      <SheetContent side="left" className="flex w-72 flex-col gap-6 bg-card p-4">
        <SheetHeader className="p-0 text-left">
          <SheetTitle>
            <Wordmark />
          </SheetTitle>
        </SheetHeader>
        <SidebarNav onNavigate={() => setOpen(false)} />
        <div className="mt-auto">
          <OrgBadge />
        </div>
      </SheetContent>
    </Sheet>
  );
};
