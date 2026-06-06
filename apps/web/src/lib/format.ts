import { format, formatDistanceToNowStrict, parseISO } from "date-fns";

/** "6 Jun 2026" — the ledger's date voice (legal-document style). */
export const formatLegalDate = (iso: string): string =>
  format(parseISO(iso), "d MMM yyyy");

/** "June 6, 2026" — long form for the as-of docket. */
export const formatDocketDate = (iso: string): string =>
  format(parseISO(iso), "MMMM d, yyyy");

export const formatRelative = (iso: string): string =>
  formatDistanceToNowStrict(parseISO(iso), { addSuffix: true });

export const formatCostUsd = (value: number | null): string =>
  value === null ? "—" : `$${value.toFixed(4)}`;

export const formatTokens = (value: number): string =>
  new Intl.NumberFormat("en-US").format(value);

export const formatConfidence = (value: number): string =>
  `${Math.round(value * 100)}%`;

/** Clause index → ledger numbering ("Clause №3"). */
export const clauseNumber = (index: number): string => `№${index + 1}`;
