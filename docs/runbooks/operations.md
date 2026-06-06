# Runbook — Routine Operations

## Tenant provisioning

```powershell
uv run chronos org create "Acme Fintech" --jurisdiction PK
uv run chronos keys create --org-id <id> --name "prod-dashboard" --scopes audit
# admin-scope keys are for n8n / operators only:
uv run chronos keys create --org-id <id> --name "n8n-monitor" --scopes admin
```

The full key prints once. Revocation = set `revoked_at` (SQL) — rotation is
create-new → switch consumer → revoke-old.

## Ingestion & the review queue

```powershell
uv run chronos ingest url https://www.secp.gov.pk/.../circular-12-2026.pdf `
    --title "SECP Circular 12 of 2026" --body SECP --type Circular `
    --jurisdiction PK --published 2026-06-01
uv run chronos worker run-once          # or let the in-process worker drain it
uv run chronos status --review          # quarantined documents + reasons
uv run chronos confirm <doc_id>         # operator judgment → retrievable
```

Quarantine reasons: `scanned_pdf` (no OCR in MVP), `non_english` (Urdu
scoping decision), `no_structure` (chunker fallback), `injection_flag`
(instruction-like text), `low_confidence`, `superseded_by_correction`.
**A quarantined document NEVER influences an audit** — the gate lives inside
the canonical temporal predicate.

## Supersession (operator-confirmed, never automatic)

When ingestion logs `supersedes_refs` suggestions, verify against the actual
gazette text, then:

```powershell
uv run chronos supersede <new_doc_id> --supersedes <old_doc_id> --relation amends
```

One atomic operation: closes the old validity intervals (retrieval), records
lineage edges (diff UI), and flags past audit runs whose verdicts the change
may invalidate (`stale=true` — surfaced in the API; recommend re-run, never
auto-rerun).

## Quality evals

```powershell
uv run pytest -m eval                          # free, deterministic fakes
$env:CG_EVAL_LIVE = "1"                        # + OPENAI_API_KEY in env
uv run pytest -m eval -s                       # real models, costs cents
```

Gates (starting values): recall@8 ≥ 0.8, MRR ≥ 0.5, verdict accuracy ≥ 0.66,
grounding drops logged as the hallucination canary.

## Contract changes (UI / n8n consumers)

Any intentional API change: `uv run chronos export-openapi`, review the
`packages/contracts/openapi.json` diff in the PR. CI fails on silent drift.
