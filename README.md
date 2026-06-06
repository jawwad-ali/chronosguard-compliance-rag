# ChronosGuard Compliance

**Temporal Compliance RAG Engine** — detects *regulatory drift* by auditing internal company
policies against the regulation that was actually **in force in a jurisdiction on a given date**.

[![CI](https://img.shields.io/badge/CI-GitHub_Actions-2088FF?logo=githubactions&logoColor=white)](./.github/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](apps/api/pyproject.toml)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Postgres + pgvector](https://img.shields.io/badge/Postgres-pgvector-4169E1?logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)
[![mypy strict](https://img.shields.io/badge/mypy-strict-blue)](apps/api/pyproject.toml)

## Why this exists

Regulators don't ship REST APIs. The legal source of truth is unstructured PDF gazettes, SROs,
and circulars. Companies in regulated industries (fintech, healthcare) drift out of compliance
as the law shifts underneath their internal policies. ChronosGuard:

1. **Ingests** regulatory PDFs into a hierarchically chunked, vector-indexed corpus —
   every chunk anchored to `[effective_date, expiration_date)` and a jurisdiction
2. **Retrieves temporally** — "what law was in force on date X" is a first-class, tested query;
   superseded and expired rules never leak into an audit
3. **Audits** policy text clause-by-clause with grounded LLM verdicts — every finding must quote
   verbatim regulatory text, verified server-side, or it is discarded
4. **Refuses to lie** — zero retrieved law yields `INSUFFICIENT_EVIDENCE`, never a false green check

## Architecture at a glance

```text
[PDF gazettes] → ingestion (extract → hierarchical chunk → LLM metadata + verification → review gate)
                        │
                        ▼
   Postgres + pgvector ── global, temporally-anchored regulatory corpus
   Row-Level Security ─── tenant-isolated policies, audit runs, findings
                        │
                        ▼
[policy text] → clause split → temporal+vector retrieval → structured-output verdicts
              → quote-grounding gate → tri-state verdict (202 + poll)
```

Deep dives: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** (full blueprint) ·
**[docs/ROADMAP.md](docs/ROADMAP.md)** (build plan with acceptance gates)

## Stack

| Layer | Choice |
|---|---|
| API | FastAPI (Python 3.12, fully async, mypy `strict`) |
| Data | PostgreSQL 16 + pgvector (HNSW), SQLModel on SQLAlchemy 2 async, Alembic |
| Multi-tenancy | Shared schema + `tenant_id` + **Postgres RLS** (fail-closed, leak-tested in CI) |
| AI | OpenAI `text-embedding-3-small` + GPT structured outputs (deterministic fakes in CI) |
| Jobs | Postgres-backed queue, lease + reaper, in-process async worker |
| Quality | ruff, mypy strict, pytest (unit / integration / RLS / contract / eval lanes) |
| Deploy | Neon + Render (managed PaaS), GitHub Actions CI |

## Quickstart (local)

Prereqs: [uv](https://docs.astral.sh/uv/), Docker Desktop.

```powershell
cd apps/api
uv sync                      # installs Python 3.12 + all deps
copy .env.example .env
uv run poe up                # Postgres 16 + pgvector via docker compose
uv run poe migrate           # apply migrations  (from Chunk 1)
uv run poe api               # http://localhost:8000/docs
```

Verify:

```powershell
uv run poe lint              # ruff check + format
uv run poe types             # mypy strict
uv run poe test              # unit lanes (no DB, no network, no OpenAI spend)
uv run poe test-all          # + integration/RLS/contract lanes (needs Docker)
```

## Project layout

```text
apps/api/            FastAPI backend (src/chronosguard)
packages/contracts/  OpenAPI snapshot — the frozen contract for the Next.js UI & n8n
infra/               docker-compose (local Postgres), render.yaml (PaaS)
docs/                ARCHITECTURE.md · ROADMAP.md · runbooks
```

## See it work (the PocketPay demo)

The same policy text audited at two points in time returns different verdicts — because the
law changed underneath it:

```text
POST /api/v1/audits  {"policy_text": "PocketPay will hold user funds for up to
                       7 business days before clearing. …",
                      "jurisdiction": "PK", "as_of_date": "2026-06-06"}
→ 202 → poll →  verdict: VIOLATIONS_FOUND
   finding[HIGH]  Regulation 12-B(4) (as amended) — SECP SRO 1234(I)/2026
   quote: "…must settle transit funds within a strict maximum window of
           three (3) business days."
   fix:   Reduce the holding window to 3 business days.

same request with "as_of_date": "2025-01-01"
→ verdict: COMPLIANT          (the old 7-day rule governed then)
```

Every finding carries a server-verified verbatim quote, a DB-sourced citation and source URL
(the LLM cannot fabricate either), and a `needs_review` flag when retrieval confidence was weak.

## Engineering highlights

- **Temporal correctness as code**: one canonical `as_of_predicate()` with an 8-case
  truth-table test (half-open intervals, amendment-day swaps, retroactive effectivity,
  review-gate exclusion)
- **Postgres RLS multi-tenancy** proven by a blocking CI lane — cross-tenant SELECT/INSERT
  isolation, fail-closed missing-context, and the background-worker write path
- **Hallucination defenses**: strict structured outputs + quote-grounding hard gate
  (ungrounded findings are dropped and counted as the canary metric)
- **Honest verdicts**: zero retrieved law ⇒ `INSUFFICIENT_EVIDENCE`, clause errors ⇒
  `partial` (never a false green check); retroactive amendments flag stored verdicts `stale`
- **Ingestion quarantine**: scanned PDFs, Urdu-primary documents, prompt-injection patterns,
  and structureless extractions are review-gated — quarantined text can never reach an audit
- **Ops**: Postgres-backed job queue (SKIP LOCKED + lease + reaper), per-call AI cost
  telemetry, circuit-breaker 503 on provider outage, OpenAPI contract freeze, Sentry with
  confidentiality scrubbing
- **300+ assertions across 174 tests** in five lanes (unit / integration / RLS / contract /
  eval) — CI spends $0 on AI

## Status

**Phase 1 (backend core): complete** — all eight roadmap chunks landed with their acceptance
gates green ([docs/ROADMAP.md](docs/ROADMAP.md)). Deploy config for Neon + Render is in
[infra/render.yaml](infra/render.yaml) with runbooks in [docs/runbooks/](docs/runbooks/).
Phase 2 (Next.js audit dashboard, n8n nightly monitor) builds against the frozen contract in
[packages/contracts/openapi.json](packages/contracts/openapi.json).
