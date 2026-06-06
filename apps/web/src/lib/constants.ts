import type { RiskLevel, RunStatus, Verdict } from "@/lib/api/types";

/** Verdict presentation — the stamp vocabulary. */
export const VERDICT_META: Record<
  Verdict,
  { label: string; tone: "compliant" | "violation" | "insufficient" }
> = {
  COMPLIANT: { label: "Compliant", tone: "compliant" },
  VIOLATIONS_FOUND: { label: "Violations Found", tone: "violation" },
  INSUFFICIENT_EVIDENCE: { label: "Insufficient Evidence", tone: "insufficient" },
};

/** Risk ladder maps directly onto the palette: tuscan → sandy → burnt peach. */
export const RISK_META: Record<RiskLevel, { label: string; rank: number }> = {
  HIGH: { label: "High", rank: 3 },
  MEDIUM: { label: "Medium", rank: 2 },
  LOW: { label: "Low", rank: 1 },
};

export const RUN_STATUS_META: Record<
  RunStatus,
  { label: string; terminal: boolean }
> = {
  queued: { label: "Queued", terminal: false },
  running: { label: "Running", terminal: false },
  succeeded: { label: "Succeeded", terminal: true },
  partial: { label: "Partial", terminal: true },
  failed: { label: "Failed", terminal: true },
};

export const AUDIT_POLL_INTERVAL_MS = 1_500;
export const DEFAULT_PAGE_SIZE = 20;
export const MAX_POLICY_BODY_CHARS = 200_000;

export const APP_NAME = "ChronosGuard";
export const APP_TAGLINE = "Temporal Compliance Ledger";
