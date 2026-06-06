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

## Status

Phase 1 (backend core) in progress — see [docs/ROADMAP.md](docs/ROADMAP.md) for chunk-by-chunk
acceptance gates. UI (Next.js) and ingestion automation (n8n) are Phase 2; their API contracts
are frozen in Phase 1.
