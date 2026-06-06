"use client";

import { format } from "date-fns";
import { CalendarDays, Loader2, SearchCheck, Sparkles } from "lucide-react";
import { useState } from "react";

import { ChunkValidity } from "@/components/regulatory/chunk-validity";
import { CitationChip } from "@/components/brand/citation-chip";
import { EmptyState } from "@/components/brand/empty-state";
import { ErrorState } from "@/components/brand/error-state";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useMe, useRegulatorySearch } from "@/lib/api/queries";
import { formatLegalDate } from "@/lib/format";
import { cn } from "@/lib/utils";

export const TemporalSearch = () => {
  const me = useMe();
  const search = useRegulatorySearch();
  const [query, setQuery] = useState("");
  const [jurisdiction, setJurisdiction] = useState("");
  const [asOf, setAsOf] = useState<Date>(new Date());

  const effectiveJurisdiction =
    (jurisdiction || me.data?.home_jurisdiction || "PK").toUpperCase();
  const canSearch = query.trim().length >= 3;

  const onSearch = (event: React.FormEvent): void => {
    event.preventDefault();
    if (!canSearch) return;
    search.mutate({
      query: query.trim(),
      jurisdiction: effectiveJurisdiction,
      as_of_date: format(asOf, "yyyy-MM-dd"),
      top_k: 10,
    });
  };

  return (
    <div className="space-y-6">
      <form
        onSubmit={onSearch}
        className="grid grid-cols-1 gap-4 rounded-lg border border-border bg-card p-4 shadow-sheet sm:grid-cols-[1fr_8rem_auto_auto] sm:items-end"
      >
        <div className="space-y-2">
          <Label htmlFor="search-query">What does the law say about…</Label>
          <Input
            id="search-query"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="holding customer funds before clearing"
            className="h-11 bg-background"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="search-jurisdiction">Jurisdiction</Label>
          <Input
            id="search-jurisdiction"
            value={jurisdiction}
            onChange={(event) => setJurisdiction(event.target.value)}
            placeholder={me.data?.home_jurisdiction ?? "PK"}
            className="h-11 bg-background uppercase"
          />
        </div>
        <div className="space-y-2">
          <Label>As of</Label>
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline" className="h-11 justify-start gap-2 font-normal">
                <CalendarDays className="h-4 w-4" aria-hidden />
                {format(asOf, "d MMM yyyy")}
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0" align="start">
              <Calendar
                mode="single"
                selected={asOf}
                onSelect={(date) => date && setAsOf(date)}
                autoFocus
              />
            </PopoverContent>
          </Popover>
        </div>
        <Button type="submit" disabled={!canSearch || search.isPending} className="h-11 gap-2">
          {search.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <SearchCheck className="h-4 w-4" aria-hidden />
          )}
          Search
        </Button>
      </form>

      {search.isError ? (
        <ErrorState error={search.error} onRetry={() => search.reset()} />
      ) : null}

      {search.isSuccess ? (
        search.data.items.length === 0 ? (
          <EmptyState
            icon={SearchCheck}
            title="No law in force matched"
            description={`Nothing in the confirmed ${search.data.jurisdiction} corpus governs this as of ${formatLegalDate(search.data.as_of_date)}.`}
          />
        ) : (
          <ol className="space-y-3">
            <p className="ledger-label">
              In force in {search.data.jurisdiction} as of{" "}
              {formatLegalDate(search.data.as_of_date)}
            </p>
            {search.data.items.map((hit) => (
              <li
                key={hit.id}
                className={cn(
                  "animate-rise rounded-lg border border-border bg-card p-4 shadow-sheet",
                  hit.weak_match && "border-dashed",
                )}
              >
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <CitationChip citation={hit.legal_citation} />
                  {hit.source === "citation" ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-accent px-2 py-0.5 text-[0.6875rem] font-semibold uppercase tracking-[0.08em] text-accent-foreground">
                      <Sparkles className="h-3 w-3" aria-hidden /> Exact citation
                    </span>
                  ) : null}
                  {hit.weak_match ? (
                    <span className="rounded-full bg-tuscan-800 px-2 py-0.5 text-[0.6875rem] font-semibold uppercase tracking-[0.08em] text-tuscan-200">
                      Weak match
                    </span>
                  ) : null}
                  {hit.score !== null ? (
                    <span className="ml-auto text-xs text-muted-foreground">
                      similarity {(hit.score * 100).toFixed(0)}%
                    </span>
                  ) : null}
                </div>
                <p className="mb-1 text-xs text-muted-foreground">{hit.heading_path}</p>
                <p className="text-sm leading-relaxed text-charcoal-400">{hit.content}</p>
                <div className="mt-3 border-t border-border pt-2">
                  <ChunkValidity
                    effective={hit.effective_date}
                    expiration={hit.expiration_date}
                    source={hit.effective_date_source}
                  />
                </div>
              </li>
            ))}
          </ol>
        )
      ) : null}

      {search.isIdle ? (
        <EmptyState
          icon={SearchCheck}
          title="Ask the corpus a question"
          description="Same query, different as-of date, different law — try it around an amendment boundary."
        />
      ) : null}
    </div>
  );
};
