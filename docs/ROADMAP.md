# ChronosGuard Compliance — Roadmap

**Phase 1 (backend core) broken into 9 chunks. Each chunk is a small win: independently
shippable, demo-able, and gated by explicit acceptance criteria. No chunk starts until the
previous chunk's gates are green.** Architecture authority: `docs/ARCHITECTURE.md`.

```text
C0 bootstrap ─▶ C1 DB+RLS ─▶ C2 auth ─▶ C3 corpus+temporal ─▶ C4 vector search
                                                                    │
        C8 eval+deploy ◀─ C7 ingestion ◀─ C6 audit pipeline ◀─ C5 policies
```

---

## Chunk 0 — Repo bootstrap & walking skeleton

**Win:** fresh clone → one command → running API + green CI.

Scope:
- Monorepo layout (`apps/api`, `packages/contracts`, `infra/`, `docs/`)
- `pyproject.toml` (uv): FastAPI, SQLModel, asyncpg, alembic, pydantic-settings, structlog,
  openai, typer, tenacity, pgvector; dev group: pytest+anyio, httpx, ruff, mypy (strict),
  testcontainers, poe tasks
- `infra/docker-compose.yml` — `pgvector/pgvector:pg16` only
- App factory + lifespan in `main.py`; `core/config.py` (Settings), `core/logging.py`
  (structlog, request-id middleware), `core/errors.py` (ProblemDetail + handlers)
- `/healthz`, `/readyz` (DB ping wired in C1)
- CI: lint → typecheck → test (empty-but-running), on PR + main
- `.env.example`, `README.md` quickstart, pre-commit (ruff + hygiene)

Acceptance gates:
- [ ] `uv sync && poe up && poe api` serves `/healthz` 200 on a clean Windows machine
- [ ] `poe lint`, `poe types`, `poe test` all green locally and in CI
- [ ] ProblemDetail returned for an unknown route (404) with `request_id`

## Chunk 1 — Database foundation & RLS spine

**Win:** migrations apply from zero; cross-tenant isolation *proven* by tests, not asserted.

Scope:
- Alembic async `env.py`; naming convention pinned; vector extension in migration 0001
- Roles migration: `cg_owner` / `cg_app` / `cg_worker` + grants (per ARCHITECTURE §3.5)
- Tables: `jurisdictions`, `organizations`, `api_keys` (no RLS — auth bootstrap), `jobs`
- `app_current_tenant()` + RLS policies (ENABLE + FORCE) on `organizations`
- `models/base.py` (timestamp mixin, metadata), single model import point
- testcontainers integration harness; migrations-from-zero per test session
- RLS test lane: SELECT isolation, WITH CHECK rejection, fail-closed on no context

Acceptance gates:
- [ ] `alembic upgrade head` from empty DB, twice (idempotent re-run guard)
- [ ] `alembic check` drift gate green in CI; `downgrade -1 && upgrade head` passes
- [ ] RLS leak tests green **connecting as non-superuser `cg_app`**
- [ ] Migration gate is a blocking CI job

## Chunk 2 — Auth, tenancy & the first tenant-scoped request

**Win:** an API key holder hits `/api/v1/me` and gets exactly their org — and nobody else's.

Scope:
- Key scheme `cgk_{env}_{prefix8}.{secret32}`; SHA-256+pepper; prefix lookup; constant-time verify
- `authenticate` → `tenant_session` (SET LOCAL via `set_config(..., true)`) → `require_scope`
  dependency chain; one session per request guaranteed
- `chronos keys create` + org provisioning CLI
- `GET /api/v1/me`; 401/403 ProblemDetail paths
- structlog binds `tenant_id` after auth

Acceptance gates:
- [ ] Two seeded orgs: key A sees org A via `/me`; key B sees org B; no key → 401; wrong scope → 403
- [ ] Revoked key rejected; `last_used_at` updates
- [ ] API-level RLS test: A cannot read B through any shipped endpoint
- [ ] Tenant id appears in every post-auth log line

## Chunk 3 — Regulatory corpus & the temporal moat

**Win:** seeded corpus browsable over HTTP; "what law was in force on date X" answered correctly
for every edge case — before any AI is involved.

Scope:
- Tables: `regulatory_documents`, `regulatory_chunks` (embedding nullable), `supersessions`
- `retrieval/temporal.py` — THE canonical `as_of_predicate()` (incl. `extraction_status`
  gate + `embedding IS NOT NULL`)
- `chronos seed` — the six fixtures from ARCHITECTURE §8.3 (fake embeddings)
- Read endpoints: documents list/detail/chunks (limit/offset)
- Truth-table unit tests + integration tests on seeds: boundary dates, expired, superseded,
  retroactive, unconfirmed-excluded

Acceptance gates:
- [ ] Table-driven temporal tests pass: exactly-on-effective in; exactly-on-expiration out;
      expired circular absent for as_of ≥ 2022; retroactive rule present for past as-of
- [ ] Supersession fixture: old rule in force as-of 2025, amendment in force as-of 2026-06
- [ ] `extraction_status='review'` chunks invisible to the predicate
- [ ] Corpus browse endpoints paginate and filter (body/type/jurisdiction)

## Chunk 4 — Embeddings & vector search

**Win:** `POST /regulatory/search` returns semantically ranked, temporally correct law.

Scope:
- `providers/` package: Protocols (with `.model`/`.dims`) + `OpenAIEmbeddings` + deterministic
  `FakeEmbeddings` (CI)
- HNSW index migration (`WHERE embedding IS NOT NULL`; built post-seed)
- `retrieval/candidates.py`: ANN top-24 → trim top-8, soft threshold + `weak_match`;
  citation-regex exact lookup; `merge_candidates()`
- `POST /api/v1/regulatory/search` (same predicate as audit)
- OpenAI call telemetry (tokens/cost/latency) in the provider wrapper

Acceptance gates:
- [ ] Search "hold customer funds before clearing" (PK, as-of 2026-06-06) ranks the 3-day
      settlement rule first; as-of 2025-01-01 returns the old 7-day rule
- [ ] `EXPLAIN` integration test proves HNSW index usage
- [ ] CI runs fully on `FakeEmbeddings` — zero OpenAI spend
- [ ] Citation lookup: a query naming "Section 12-B" surfaces that chunk regardless of vector rank

## Chunk 5 — Tenant policies

**Win:** tenants store versioned policy documents under RLS.

Scope:
- Tables + RLS: `org_policies`, `org_policy_versions` (immutable versions; PATCH ⇒ new version)
- CRUD endpoints + pagination; soft-delete policy retirement
- RLS lane extended to both tables

Acceptance gates:
- [ ] Full CRUD via API; version increments on body change; old versions immutable
- [ ] Cross-tenant: B's policy ids 404 for A (not 403 — no existence leak)
- [ ] OpenAPI snapshot updated + contract test green

## Chunk 6 — The audit pipeline (the core loop) 🎯

**Win:** the spec's PocketPay demo, live: `POST /audits` → 202 → poll → grounded HIGH violation
with correct citation — and the same audit as-of 2025 comes back compliant.

Scope:
- Tables + RLS: `audit_runs` (status/verdict/coverage/stale/cost/clause snapshot JSONB),
  `audit_findings`
- Worker: lifespan asyncio drainer; claim via `FOR UPDATE SKIP LOCKED`; lease + startup/periodic
  reaper; **per-job tenant context** (`cg_worker` engine)
- `retrieval/policy_split.py` (clause splitter); `audit/prompt.py` (JSON excerpt array, ref_id,
  6k-token budget, as-of injection); `audit/schema.py` (strict ClauseVerdict);
  `audit/grounding.py` (quote verification hard gate); `audit/pipeline.py` (fan-out,
  Semaphore(5)); rollup rules (tri-state + coverage + partial)
- `OpenAIChat` structured-outputs provider + `FakeChat` (canned verdicts)
- Endpoints: POST/GET audits, findings listing; per-run cost persisted
- Sanitization of delimiter-lookalike tokens at context assembly
- RLS lane: **worker-path INSERT test** (the design-review blocker — proven fixed)

Acceptance gates:
- [ ] E2E on seeds: PocketPay 7-day-hold policy → as-of 2026-06-06 → `VIOLATIONS_FOUND`, HIGH,
      citation "Section 12-B…", correct `source_url` from DB; as-of 2025-01-01 → `COMPLIANT`
- [ ] Empty-corpus jurisdiction → `INSUFFICIENT_EVIDENCE`, never compliant
- [ ] Fabricated-quote fixture (FakeChat returns an ungrounded finding) → finding dropped,
      grounding canary logged
- [ ] Clause LLM failure fixture → `status=partial`, verdict ≠ COMPLIANT
- [ ] Kill the worker mid-run → reaper requeues; job completes on restart
- [ ] Worker RLS test: findings INSERT succeeds under job context, fails without
- [ ] Full CI run with fakes — zero OpenAI spend

## Chunk 7 — Ingestion pipeline

**Win:** a real SECP circular goes from URL to retrievable, temporally-anchored chunks.
**Starts by ingesting 5–10 real gazettes to validate heuristics before locking them.**

Scope:
- `ingestion/`: fetch (httpx, ETag fast-path), extract (pymupdf4llm), scanned + non-English
  detection → review reasons; hierarchical chunker (heading tree, breadcrumb injection,
  300–800 token bounds, fallback); metadata extraction (rule pre-pass + LLM structured outputs +
  evidence-substring verification + `effective_date_source`); injection-pattern quarantine;
  dedup/versioning (`(source_url, content_hash)`); batched resumable embedding
- Supersession suggest + `chronos supersede` confirm (atomic close+edge) + **staleness flagger**
  over past runs
- Admin endpoints: `POST /admin/ingest` (hints-only body), `GET /admin/ingest/{job_id}` —
  the n8n contract, live
- Full CLI surface (`ingest`, `status`, `confirm`, `supersede`, `reindex`,
  `backfill-embeddings`, `retry`)

Acceptance gates:
- [ ] 5–10 real SECP/SBP PDFs ingested; chunker output eyeballed + golden-file tested
- [ ] Same URL re-ingest → no-op; altered content → version 2, v1 chunks expired not mutated
- [ ] Scanned PDF → `review: scanned_pdf`; Urdu doc → `review: non_english`; neither produces chunks
- [ ] Undated doc → `defaulted_to_published` provenance; unconfirmed docs never retrievable
- [ ] Supersede confirm closes intervals + inserts edge + flags affected past runs `stale`
- [ ] Crash mid-embedding → `backfill-embeddings` completes without re-embedding done chunks
- [ ] n8n-shaped webhook POST (admin key) → 202 → job poll → confirmed doc retrievable

## Chunk 8 — Eval harness, hardening & production deploy

**Win:** measured quality baseline + a live prod URL running the seeded demo.

Scope:
- `eval/golden/` JSONL (rules + labeled cases incl. temporal pairs); `pytest -m eval`:
  recall@8, MRR, verdict confusion matrix, grounding pass rate
- Sentry (with exception-args/extra/SQL-params scrubbing); redaction processor for
  `policy_text`/`content`/`embedding`
- Connection-budget startup assertion; OpenAI-degraded 503 gate on `POST /audits`
- `render.yaml` + Neon prod provisioning (roles, direct endpoint); deploy pipeline
  (pre-deploy migrations, health-gated cutover); `pip-audit` advisory lane
- Runbooks: rollback-via-Neon-PITR, tenant provisioning, review-queue triage
- `openapi.json` exported to `packages/contracts/` (the Phase-2 frontend contract)

Acceptance gates:
- [ ] Eval baseline recorded (target: recall@8 ≥ 0.9, verdict accuracy ≥ 0.85 on golden set —
      numbers are starting gates, tuned thereafter)
- [ ] Prod URL: `/readyz` green; PocketPay demo runs end-to-end against prod
- [ ] Secrets only in Render/Actions; `.env` nowhere in history
- [ ] Rollback runbook executed once as a drill (restore branch, redeploy)

---

## Phase 2 (separate planning cycle — contracts already frozen)

| Track | Seed |
|---|---|
| Next.js audit dashboard | `packages/contracts/openapi.json`; diff view consumes `findings[]` (`grounding_quote`, `legal_citation`, `source_url`, `needs_review`, `stale`); 202+poll pattern |
| n8n nightly monitor | `POST /api/v1/admin/ingest` with admin key; SECP/SBP index-page diff workflow |
| Review-queue admin UI | `extraction_status='review'` + reasons already queryable |
| Tenant offboarding hard-delete | ADR in ARCHITECTURE §8.5 |
| Deferred register | ARCHITECTURE §11 — each item has its trigger |

## Working agreements

1. **The temporal predicate has one home.** Any PR adding a second date-filter implementation
   is rejected.
2. **No stored `is_active`.** In-force is derived. Ever.
3. **RLS lane is blocking.** A red leak test is a security incident.
4. **CI never spends OpenAI money.** Fakes in CI; real calls in manual eval runs only.
5. **Legal temporal fields are never caller-supplied.** Extraction + verification + review gate.
6. **Spec deviations get recorded** in ARCHITECTURE §12, not silently shipped.
