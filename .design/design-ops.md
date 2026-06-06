The spec is read. I have what I need to design the Ops/Quality/Delivery domain. Returning the design as raw markdown.

# Ops, Quality & Delivery — ChronosGuard Compliance

This domain owns everything between "code written" and "code running safely in prod": repo shape, tooling, tests (with RLS leak tests as a hard gate), the Windows-11 inner loop, CI/CD on GitHub Actions, observability, security posture, environments, and cost. Decisions are made; rationale is one line each.

## 1. Repo strategy

**Decision: single Git repo, polyglot monorepo, no monorepo build tooling (no Nx/Turborepo) at MVP.** One repo keeps backend + future Next.js + n8n contracts versioned together so an API change and its consumer move atomically; build tooling is deferred because two packages don't justify a graph engine.

```
chronosguard/
├─ apps/
│  ├─ api/                      # FastAPI backend (the only shipping app at MVP)
│  │  ├─ src/chronosguard/
│  │  │  ├─ main.py             # app factory, middleware wiring
│  │  │  ├─ config.py           # pydantic-settings Settings
│  │  │  ├─ db/                 # engine, session, RLS context, base models
│  │  │  ├─ models/             # SQLModel tables (regulatory_*, org_*, audit_*)
│  │  │  ├─ ingestion/          # parser, hierarchical chunker, embed pipeline
│  │  │  ├─ retrieval/          # temporal+vector query builder (the moat)
│  │  │  ├─ audit/              # RAG audit service, prompt assembly
│  │  │  ├─ providers/          # OpenAI abstraction (embeddings, chat)
│  │  │  ├─ api/v1/             # routers, request/response schemas
│  │  │  ├─ observability/      # structlog, request/tenant middleware, OpenAI metering
│  │  │  └─ cli.py              # typer ingestion CLI
│  │  ├─ migrations/            # alembic (versions/, env.py)
│  │  ├─ tests/                 # unit/ integration/ contract/ rls/
│  │  └─ pyproject.toml
│  └─ web/                      # Next.js — DEFERRED (post-MVP), empty placeholder + README
├─ packages/
│  └─ contracts/               # OpenAPI snapshot + generated TS types (the API/UI/n8n contract)
├─ automation/n8n/             # exported workflow JSON — DEFERRED, contract only (webhook payload schema)
├─ infra/
│  ├─ docker-compose.yml       # local Postgres+pgvector ONLY
│  └─ render.yaml              # PaaS service definition
├─ .github/workflows/ci.yml
├─ justfile                    # task runner
├─ .env.example
├─ .pre-commit-config.yaml
└─ README.md
```

**`apps/api/pyproject.toml` (uv, PEP 621):**

```toml
[project]
name = "chronosguard-api"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115", "uvicorn[standard]>=0.32",
  "sqlmodel>=0.0.22", "sqlalchemy[asyncio]>=2.0.36", "asyncpg>=0.30",
  "pgvector>=0.3.6", "alembic>=1.14",
  "pydantic-settings>=2.6", "structlog>=24.4",
  "openai>=1.57", "typer>=0.15", "pymupdf>=1.24", "tenacity>=9.0",
]
[dependency-groups]   # uv-native dev deps, not installed in prod image
dev = ["pytest>=8.3","pytest-anyio>=0.0","anyio>=4.6","httpx>=0.28",
       "ruff>=0.8","mypy>=1.13","pip-audit>=2.7","testcontainers[postgres]>=4.8"]

[tool.ruff]
line-length = 100
target-version = "py312"
[tool.ruff.lint]
select = ["E","F","I","UP","B","SIM","ASYNC","S","RUF","TID","PL"]
ignore = ["PLR09"]            # complexity thresholds: too noisy day-1
[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101"]         # asserts allowed in tests

[tool.mypy]
python_version = "3.12"
strict = true                 # DECISION: strict from day 1 on greenfield — cheap now, brutal to retrofit
plugins = ["pydantic.mypy"]
[[tool.mypy.overrides]]
module = ["pgvector.*"]       # untyped third-party
ignore_missing_imports = true

[tool.pytest.ini_options]
addopts = "-ra --strict-markers"
markers = ["unit","integration","rls","contract","eval"]
anyio_mode = "auto"
```

**Pre-commit stance: lightweight and fast — ruff (lint+format) + a no-network mypy hook + standard hygiene (trailing whitespace, EOF, large-file guard, detect-private-key).** Heavy checks (tests, pip-audit, migration drift) live in CI, not the commit path, so the local loop stays sub-second. Pre-commit is *recommended but not enforced* locally; CI is the source of truth so a missing local hook can't ship a regression.

## 2. Testing strategy

The pyramid is shaped by the one thing that makes this product correct: **temporal+tenant-scoped retrieval**. Pure logic is unit-tested fast; anything touching `pgvector` or RLS must hit real Postgres because both are Postgres-specific behaviors a SQLite/in-memory fake cannot fake.

**Unit (fast, no DB, the broad base):**
- *Hierarchical chunker* — given Markdown with Part/Chapter/Section headings, asserts split boundaries, citation paths, and that no chunk exceeds the token ceiling.
- *Temporal predicates* — the `effective_date <= t AND (expiration is null OR expiration > t) AND is_active` logic extracted as a pure SQLAlchemy expression builder, asserted against a truth table of boundary dates (exactly-on effective date, exactly-on expiration, superseded rule). This is the moat; it gets exhaustive table-driven coverage.
- *Services with fakes* — audit service runs against a `FakeOpenAIProvider` (canned embeddings + canned Structured-Output JSON) and a fake retrieval port, asserting prompt assembly, violation mapping, and the empty-results → `is_compliant=True` path. No network in unit lane.

**Integration (real Postgres + pgvector):**
- **Mechanics — DECISION: `testcontainers` spinning `pgvector/pgvector:pg16` locally AND in CI.** One mechanism for both environments beats maintaining two; the container is hermetic, parallel-safe, and needs no Neon credentials in CI. **Neon branch-per-PR is DEFERRED (post-MVP)** — it buys prod-parity and seeded-data testing but costs branch orchestration and secrets management that a weeks-long MVP shouldn't carry. We keep the upgrade path open by pinning the same PG major (16) and the pgvector version in both compose and the test container.
- Each integration test runs Alembic migrations on a fresh container schema (not `create_all`) so migrations themselves are exercised. Tests cover the real cosine-distance ordering, the HNSW/IVFFlat index being used (assert via `EXPLAIN`), and global-corpus visibility.

**RLS / cross-tenant leak tests — MANDATORY, own marker `rls`, blocking in CI:**
- Tests connect as a **non-superuser, non-`BYPASSRLS` app role** (superusers silently bypass RLS — a test that passes as superuser proves nothing). Seed two tenants A and B with policies, audit runs, and findings.
- Assertions: with `SET app.tenant_id = A`, queries return only A's tenant-scoped rows; B's are invisible at the SQL layer. A direct `SELECT * FROM org_policies` with tenant B context returns zero of A's rows. Global `regulatory_chunks` remain visible to both.
- Negative tests: attempting `INSERT`/`UPDATE` of a row with a mismatched `tenant_id` is rejected by the RLS `WITH CHECK` policy. A test with *no* tenant context set must return zero tenant-scoped rows (fail-closed, never fail-open).

**Contract tests:** snapshot the generated OpenAPI JSON into `packages/contracts/openapi.json`; a test fails CI if the live schema drifts from the snapshot without an intentional regeneration. This is the freeze on the UI/n8n contract — the consumers aren't built yet, so the schema *is* the integration test.

**RAG eval suite — separate, NON-BLOCKING CI lane (`-m eval`).** Owned by the RAG domain (golden Q/jurisdiction/date → expected-citation set, scored on retrieval recall@k and temporal-correctness). It runs against real OpenAI, costs money and is non-deterministic, so it runs nightly + on-demand and posts scores as a PR comment; it never blocks merge. A regression there is a signal, not a stop.

**Coverage stance: measure, don't gate on a global number.** A blanket 80% gate invites tests-for-coverage. Instead: hard requirement that `retrieval/`, `audit/`, and the RLS policies have tests (enforced by the existence of the `rls`/`integration` markers in CI, not a percentage). Coverage is reported to PR for visibility only.

## 3. Windows 11 dev experience

**`infra/docker-compose.yml` — Postgres+pgvector only** (API runs natively via uv for fast reload on Windows; no app container locally):

```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: chronos
      POSTGRES_PASSWORD: chronos
      POSTGRES_DB: chronosguard
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U chronos -d chronosguard"]
      interval: 5s
      retries: 10
volumes: { pgdata: {} }
```

**Task runner — DECISION: `just` (justfile).** It is a single static binary, installs cleanly on Windows via `winget`/`scoop`, and gives identical recipes locally and in CI without PowerShell-vs-bash drift. `poe` was the runner-up (one less binary, lives in pyproject) but couples task running to Python and is weaker for cross-tool orchestration. Recipes shell out to `uv run` so contributors never manage venvs by hand:

```just
set shell := ["pwsh", "-NoProfile", "-Command"]   # Windows-native; CI overrides to bash
up:        docker compose -f infra/docker-compose.yml up -d
down:      docker compose -f infra/docker-compose.yml down
bootstrap: uv sync; cp .env.example .env; just up; just migrate
migrate:   uv run alembic upgrade head
revise m:  uv run alembic revision --autogenerate -m "{{m}}"
lint:      uv run ruff check . ; uv run ruff format --check .
types:     uv run mypy src
test:      uv run pytest -m "not eval"
test-rls:  uv run pytest -m rls
seed:      uv run python -m chronosguard.cli seed-demo
run:       uv run uvicorn chronosguard.main:app --reload
```

**Env bootstrap:** `just bootstrap` is the one command a new dev runs — sync deps, copy `.env.example` → `.env`, start the DB, migrate. **.env handling:** `pydantic-settings` reads `.env` locally and process env in PaaS; `.env` is git-ignored, `.env.example` is committed and is the documented contract. Secrets never enter the repo; the only local secret is `OPENAI_API_KEY`.

## 4. CI/CD — GitHub Actions

**PaaS — DECISION: Render.** It pairs cleanly with Neon (both managed Postgres-friendly), gives a declarative `render.yaml` (infra-as-code, reviewable in PR), native health-check-gated zero-downtime deploys, and managed secrets — without Fly's machine/Docker ceremony or Railway's lighter operational guarantees. The API ships as a Docker image so the runtime is pinned and portable if we ever move off Render.

**Pipeline (`.github/workflows/ci.yml`) — staged, fail-fast, cheap-checks-first:**

```
on: pull_request, push(main)

job lint        → uv sync; ruff check + format --check
job typecheck   → mypy src                              (needs: -, parallel with lint)
job unit        → pytest -m unit                        (needs: lint, typecheck)
job integration → services: pgvector/pgvector:pg16
                  alembic upgrade head; pytest -m "integration or rls or contract"
job migration   → MIGRATION SAFETY GATE (see below)     (parallel with integration)
job deploy      → only on push(main), needs all green   → Render deploy hook
```

- **Migration safety gate** (separate job, blocking): spin an ephemeral pgvector service, run `alembic upgrade head` (proves migrations apply from zero), then `alembic check` — the autogenerate-drift check. If the models and the migration history disagree, the job fails. This catches the classic "edited a model, forgot the migration" bug before it reaches a deploy. We also assert `alembic downgrade -1 && upgrade head` on the latest revision to keep rollbacks real.
- **RLS lane is inside the blocking `integration` job**, not optional — a cross-tenant leak is a security incident, not a flaky test.
- **Eval lane** is a *separate workflow* on `schedule: nightly` + `workflow_dispatch`, with `continue-on-error: true` semantics and a PR-comment reporter. Never on the merge path.
- **Deploy mechanics:** on green `main`, CI calls Render's deploy hook (or `render.yaml` autodeploy with "wait for CI" enabled). Render runs `alembic upgrade head` as a **pre-deploy command** against prod Neon, then health-check-gates the new instance before cutover. Migrations are forward-only and **expand/contract** (add columns nullable → backfill → switch → drop later) so a migration never breaks the currently-running version mid-deploy.

## 5. Observability

**structlog — DECISION: JSON renderer in prod, `ConsoleRenderer` (pretty, colored) when `ENV=local`.** One config, branch on env:

```python
processors = [
    structlog.contextvars.merge_contextvars,         # request_id + tenant_id flow in here
    structlog.processors.add_log_level,
    structlog.processors.TimeStamper(fmt="iso"),
]
renderer = (structlog.dev.ConsoleRenderer() if settings.env == "local"
            else structlog.processors.JSONRenderer())
```

- **Request id + tenant id propagation:** an ASGI middleware reads/creates `X-Request-ID`, resolves the authenticated tenant, and binds both via `structlog.contextvars.bind_contextvars` so **every** log line in the request — including deep in retrieval and the OpenAI provider — carries `request_id` and `tenant_id` with zero plumbing. The same `request_id` is echoed in the response header for client-side correlation.
- **OpenAI call logging (per audit, day-1 critical):** the provider wrapper emits one structured event per call — `model`, `operation` (embed|chat), `prompt_tokens`, `completion_tokens`, `total_tokens`, computed `cost_usd` (tokens × pinned price table), `latency_ms`, `request_id`, `tenant_id`. An audit aggregates these into an `audit.completed` event with total cost and token count, persisted on the `audit_runs` row. This is the single most important signal for a RAG product: per-tenant cost and latency visibility from the first request.
- **Sentry — DECISION: IN.** Free tier covers an MVP, the FastAPI integration is ~5 lines, and unhandled-exception + trace visibility in a multi-tenant system is worth far more than it costs. Scrub `policy_text` and `content` from Sentry events (see PII rules) via `before_send`.
- **Health vs readiness:** `/healthz` (liveness — process up, no dependencies, for Render's restart probe) and `/readyz` (readiness — `SELECT 1` against Postgres + cheap OpenAI key presence check, for traffic gating). Distinct so a DB blip restarts nothing but does stop routing.
- **Minimal metrics day-1:** no Prometheus/Grafana stack (DEFERRED). The metrics that matter — audit latency, OpenAI cost per audit, error rate, per-tenant audit volume — come from structured-log aggregation in the PaaS log viewer + Sentry. A metrics backend is a post-MVP add once query volume justifies it.

## 6. Security posture

- **Secrets management:** Render environment groups / Neon dashboard hold `DATABASE_URL`, `OPENAI_API_KEY`, `SENTRY_DSN`, `API_KEY_PEPPER`. Nothing secret in the repo or image; CI uses GitHub Actions encrypted secrets. `.env` git-ignored.
- **API key hashing:** tenant API keys are stored as **SHA-256(key + server-side pepper)**, never plaintext; lookup is by hash. Argon2 is overkill here because the key is high-entropy (a random 32-byte token), not a human password — a fast hash is correct. The plaintext is shown once at issuance.
- **PII / confidentiality stance:** org `policy_text` and regulatory `content` are confidential and **must never be logged in full**. The structlog pipeline includes a redaction processor that drops/truncates any `policy_text`/`content`/`embedding` keys to a length-prefixed hash (e.g. `"<redacted len=812 sha=ab12…>"`). Sentry `before_send` applies the same scrub. Logs carry IDs and metrics, never the regulated text.
- **Dependency audit:** `pip-audit` (and `uv`'s lockfile) runs in CI as a **non-blocking warning lane** at MVP — it surfaces CVEs as a PR comment without blocking a hotfix on an unrelated transitive advisory. Promote to blocking once the dependency set stabilizes.
- **RLS as defense-in-depth:** the app sets `SET LOCAL app.tenant_id` per request inside the transaction; RLS policies enforce isolation at the database even if an application query forgets a `WHERE tenant_id`. App connects as a non-`BYPASSRLS` role. (Tested per §2.)
- **CORS:** locked allowlist driven by `CORS_ORIGINS` env — `http://localhost:3000` locally, the Vercel/Render web origin in prod. No wildcard with credentials, ever. The future Next.js app's origin is the only entry.
- **Backup/restore reality on Neon:** Neon's **point-in-time restore** (retention window per plan, ~7 days on paid) is our backup — no custom dump cron at MVP. Restore drill: branch from a past timestamp, verify, promote. We document the restore runbook now; we do *not* hand-roll backups.

## 7. Environments

**DECISION: two environments at MVP — `local` and `prod`. Staging is DEFERRED.** A dedicated staging environment doesn't earn its operational cost for a small team shipping in weeks; **Neon DB branching + Render PR preview deploys give us ephemeral, per-PR "staging" for free** when we want it, which is strictly better than one stale shared staging box. We add a long-lived staging only when a paying customer needs a UAT environment.

**Config strategy:** one `Settings` class (pydantic-settings), one set of keys, value source differs by env — `.env` file locally, PaaS env vars in prod. `ENV ∈ {local, prod}` switches log renderer, CORS origins, and Sentry enablement. No per-env code branches beyond what `Settings` expresses.

## 8. Cost reality check (modest usage)

Assumptions: 1 small team, ~2k audits/month, each audit = 1 embedding (~800 tok) + 1 GPT structured-output call (~4k in / ~1k out), corpus ~50k chunks embedded once.

| Item | Plan / usage | Est. monthly |
|---|---|---|
| Neon Postgres + pgvector | Launch/paid tier (PITR + branching) | ~$19–25 |
| Render | Starter web service (always-on, no cold start) | ~$7–25 |
| OpenAI embeddings | text-embedding-3-small, corpus + queries | < $2 |
| OpenAI GPT audits | ~2k audits × ~5k tok (gpt-class structured outputs) | ~$25–60 |
| Sentry | Free tier | $0 |
| **Total** | | **~$55–110 / month** |

OpenAI is the variable cost and the reason the per-audit token/cost logging in §5 exists from day one — it lets us see cost-per-tenant before it becomes a surprise on the invoice.

## Open risks in my domain

- **`testcontainers` on Windows dev machines** needs Docker Desktop running and can be slow to start; CI is fine, but a contributor without Docker can't run the integration/RLS lane locally — mitigated by `just up` reusing the compose Postgres, but the two paths can drift.
- **Neon PITR is the *only* backup.** If the retention window is misconfigured or a logical-corruption bug ages past the window before detection, data is unrecoverable. A weekly `pg_dump` to object storage is the cheap insurance we've deferred — revisit before first paying customer.
- **RLS correctness depends on the app *always* setting tenant context** before any tenant-scoped query; a code path that opens a session without the middleware (e.g. the ingestion CLI, background jobs) could either leak or fail-closed unexpectedly. The fail-closed default and leak tests mitigate, but coverage of *every* session-acquisition path is the real guarantee and is easy to miss.
- **Non-blocking eval + pip-audit lanes can be ignored.** Lanes that don't block merge tend to rot; without a ritual (someone owns the nightly eval/audit report), regressions and CVEs accumulate silently.
- **Migration expand/contract discipline is process, not enforced.** The drift gate catches *missing* migrations but cannot catch a *destructive* one (a `DROP COLUMN` in the same deploy that still-running code reads). This relies on reviewer vigilance until/unless we add a migration linter (e.g. squawk-style) — deferred.