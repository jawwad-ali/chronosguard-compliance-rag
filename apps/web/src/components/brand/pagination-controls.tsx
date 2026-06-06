"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";

interface PaginationControlsProps {
  total: number;
  offset: number;
  limit: number;
  onOffsetChange: (offset: number) => void;
}

export const PaginationControls = ({
  total,
  offset,
  limit,
  onOffsetChange,
}: PaginationControlsProps) => {
  if (total <= limit) return null;

  const page = Math.floor(offset / limit) + 1;
  const pages = Math.ceil(total / limit);

  return (
    <nav aria-label="Pagination" className="flex items-center justify-between">
      <p className="text-xs text-muted-foreground">
        Page <span className="font-semibold text-foreground">{page}</span> of {pages} ·{" "}
        {total} entries
      </p>
      <div className="flex gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={offset === 0}
          onClick={() => onOffsetChange(Math.max(0, offset - limit))}
          className="gap-1"
        >
          <ChevronLeft className="h-3.5 w-3.5" aria-hidden /> Prev
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={offset + limit >= total}
          onClick={() => onOffsetChange(offset + limit)}
          className="gap-1"
        >
          Next <ChevronRight className="h-3.5 w-3.5" aria-hidden />
        </Button>
      </div>
    </nav>
  );
};
