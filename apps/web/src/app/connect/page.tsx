import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { ConnectForm } from "@/app/connect/connect-form";
import { VerdictStamp } from "@/components/brand/verdict-stamp";
import { Wordmark } from "@/components/brand/wordmark";
import { getApiKey } from "@/lib/server/session";

export const metadata: Metadata = { title: "Connect" };

export default async function ConnectPage() {
  if (await getApiKey()) redirect("/");

  return (
    <main className="relative z-10 flex min-h-screen flex-col lg:flex-row">
      {/* The ink panel — the ledger's cover */}
      <section className="relative flex flex-col justify-between gap-10 bg-charcoal-500 px-6 py-10 sm:px-10 lg:w-[44%] lg:py-14">
        <Wordmark size="lg" inverted />

        <div className="space-y-6">
          <h1 className="max-w-md text-3xl font-semibold leading-snug tracking-tight text-tuscan-900 sm:text-4xl">
            What law was in force{" "}
            <span className="text-verdigris-600">on that date?</span>
          </h1>
          <p className="max-w-md text-sm leading-relaxed text-charcoal-800">
            ChronosGuard audits your internal policies against the regulation that
            actually governed — clause by clause, with verbatim, server-verified
            citations from the official gazettes.
          </p>
          <div className="flex flex-wrap items-center gap-4 pt-2" aria-hidden>
            <VerdictStamp verdict="COMPLIANT" />
            <VerdictStamp verdict="VIOLATIONS_FOUND" />
            <VerdictStamp verdict="INSUFFICIENT_EVIDENCE" />
          </div>
        </div>

        <p className="text-xs text-charcoal-700">
          Honest verdicts only — zero retrieved law is never reported as compliant.
        </p>
      </section>

      {/* The paper panel — the form */}
      <section className="flex flex-1 items-center justify-center px-6 py-12 sm:px-10">
        <div className="w-full max-w-md animate-rise space-y-8">
          <div className="space-y-2">
            <p className="ledger-label">Open the ledger</p>
            <h2 className="text-2xl font-semibold tracking-tight text-charcoal-400">
              Connect your organization
            </h2>
            <p className="text-sm text-muted-foreground">
              Paste an organization API key. It is stored in an httpOnly cookie on
              this device only — browser scripts can never read it.
            </p>
          </div>
          <ConnectForm />
          <p className="text-xs text-muted-foreground">
            Need a key? An operator can issue one:{" "}
            <code className="rounded bg-secondary px-1.5 py-0.5 text-[0.6875rem]">
              chronos keys create --org-id 1 --scopes audit
            </code>
          </p>
        </div>
      </section>
    </main>
  );
}
