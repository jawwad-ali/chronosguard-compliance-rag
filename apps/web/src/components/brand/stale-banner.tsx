import { History } from "lucide-react";

/**
 * A stored verdict the law later changed underneath (retroactive amendment).
 * ChronosGuard never lets a verdict silently rot — this banner is the receipt.
 */
export const StaleBanner = () => (
  <div
    role="alert"
    className="flex items-start gap-3 rounded-md border border-sandy-500/50 bg-sandy-900 px-4 py-3"
  >
    <History className="mt-0.5 h-4 w-4 shrink-0 text-sandy-300" aria-hidden />
    <div className="space-y-0.5 text-sm">
      <p className="font-semibold text-sandy-200">
        This verdict may be affected by a later retroactive amendment.
      </p>
      <p className="text-sandy-300/90">
        Regulation reasoned over by this run was superseded with an effective date
        inside the run&apos;s window. Re-run the audit for a current verdict.
      </p>
    </div>
  </div>
);
