I have the spec. Now I'll write the API & Service Architecture design.

# ChronosGuard — API & Service Architecture

## 0. Domain decisions (TL;DR)

| Concern | Decision | Rationale |
|---|---|---|
| Layering | routers → services → **thin repositories only for RLS-sensitive + vector queries**; simple CRUD lives in services | Repository-everywhere is enterprise cosplay at MVP; isolate the queries that are genuinely tricky/security-critical |
| ORM session | async `AsyncEngine` + `async_sessionmaker`, one session per request via dependency, transaction = request | Matches SQLModel-on-SQLAlchemy-2.x async + asyncpg |
| Pooler | **Neon direct (non-pooled) endpoint** for the API; `statement_cache_size=0` defensively | Avoids PgBouncer-transaction-mode prepared-statement breakage; `SET LOCAL` tenancy needs same connection as the txn |
| Tenancy | API key → tenant_id → `SET LOCAL app.tenant_id` inside the request txn → Postgres RLS | LOCKED; this is the load-bearing security control |
| Auth | **Org-scoped API keys**, SHA-256 hashed, prefix-indexed, scope enum (`read`/`audit`/`admin`). User-level auth DEFERRED | Smallest credible scheme; n8n + Next.js both speak API keys trivially |
| Long audit | **202 + poll** (`audit_runs` job row). Sync path retained only for tiny ad-hoc text | LLM round-trips are seconds-to-minutes; sync ties up a worker and dies on PaaS request timeouts |
| Pagination | **Keyset/cursor** on opaque `(sort_key, id)` token | Stable under concurrent ingestion; offset rots |
| Errors | RFC 9457 `application/problem+json`, single exception hierarchy, global handlers | One obvious way; Next.js parses one shape |
| Versioning | `/api/v1` path prefix | Boring, visible, cache-friendly |

---

## 1. Backend directory tree (src layout)

```text
chronosguard/
├── pyproject.toml                # uv-managed; ruff + mypy + pytest config
├── alembic.ini
├── docker-compose.yml            # local Postgres+pgvector only
├── migrations/                   # Alembic; includes raw SQL for RLS policies & pgvector index
│   ├── env.py                    # async engine, imports SQLModel.metadata
│   └── versions/
├── src/
│   └── chronosguard/
│       ├── __init__.py
│       ├── main.py               # FastAPI app factory, lifespan, router include, handler registration
│       ├── core/
│       │   ├── config.py         # pydantic-settings Settings (env-driven, cached)
│       │   ├── db.py             # async engine, async_sessionmaker, get_session dependency
│       │   ├── tenancy.py        # tenant-context dependency: SET LOCAL app.tenant_id
│       │   ├── security.py       # API key hash/verify, scope check, auth dependency
│       │   ├── logging.py        # structlog config + request-id/tenant-id binding
│       │   ├── errors.py         # AppError hierarchy + RFC9457 ProblemDetail + handlers
│       │   ├── pagination.py     # cursor encode/decode, Page[T] envelope
│       │   └── ids.py            # ULID generation for public ids + idempotency keys
│       ├── models/               # SQLModel table=True ORM models (DB truth)
│       │   ├── base.py           # TimestampMixin, TenantMixin, table naming
│       │   ├── tenant.py         # Tenant, ApiKey
│       │   ├── regulatory.py     # RegulatoryDocument, RegulatoryChunk (GLOBAL)
│       │   ├── policy.py         # OrgPolicy (tenant-scoped)
│       │   └── audit.py          # AuditRun, AuditFinding (tenant-scoped)
│       ├── schemas/              # Pydantic v2 request/response DTOs (API contract; NOT tables)
│       │   ├── common.py         # Page, CursorParams, ProblemDetail, HealthStatus
│       │   ├── auth.py
│       │   ├── policy.py
│       │   ├── regulatory.py
│       │   ├── audit.py
│       │   └── ingestion.py
│       ├── repositories/         # ONLY: RLS-scoped + vector + keyset queries
│       │   ├── regulatory.py     # temporal+vector retrieval, corpus browse keyset
│       │   ├── policy.py         # tenant-scoped CRUD relying on RLS
│       │   └── audit.py          # audit_run lifecycle, findings, idempotency lookup
│       ├── services/             # business logic / orchestration
│       │   ├── audit_service.py  # retrieval → prompt → structured-output → persist findings
│       │   ├── retrieval_service.py # embeds query, temporal filter, ranks chunks
│       │   ├── policy_service.py
│       │   ├── ingestion_service.py # parse→chunk→embed→upsert (shared by CLI + admin route)
│       │   └── provider/         # thin AI abstraction (LOCKED: OpenAI)
│       │       ├── base.py       # EmbeddingProvider, ChatProvider Protocols
│       │       └── openai.py     # text-embedding-3-small + Structured Outputs impl
│       ├── routers/
│       │   ├── health.py         # /healthz, /readyz
│       │   ├── audit.py          # /api/v1/audits (create 202, get, list, findings)
│       │   ├── policies.py       # /api/v1/policies CRUD
│       │   ├── regulatory.py     # /api/v1/regulatory/documents + /chunks + /search
│       │   └── admin.py          # /api/v1/admin/ingest (admin scope; n8n contract)
│       ├── workers/
│       │   └── audit_runner.py   # in-process background executor for audit jobs (MVP)
│       └── cli/
│           └── ingest.py         # typer CLI: ingest-doc, reindex, expire-rule
└── tests/
    ├── conftest.py               # async client, ephemeral Neon branch / docker pg, seeded tenants
    ├── test_tenancy_rls.py       # CRITICAL: cross-tenant isolation proof
    ├── test_auth.py
    ├── test_audit_flow.py
    ├── test_retrieval_temporal.py
    └── test_errors.py
```

**Repository-layer ruling:** Services own trivial single-table CRUD directly via the session (no ceremony). A repository earns its place in exactly three spots: (1) the **temporal+vector retrieval** query (complex, perf-critical, must be unit-tested against fixtures), (2) **tenant-scoped reads/writes** where centralizing the query keeps the RLS assumption auditable in one file, and (3) **keyset pagination** assembly. This is the minimum that prevents copy-pasted `WHERE` clauses around the security boundary.

---

## 2. Async session management

`core/db.py`:

```python
from collections.abc import AsyncIterator
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from chronosguard.core.config import settings

# Neon: use the DIRECT (non-pooled) host for the API.
# asyncpg + Neon/PgBouncer: disable client-side prepared-statement cache to avoid
# "prepared statement already exists" under any pooled endpoint, and to keep SET LOCAL
# bound to the same physical connection as the transaction.
engine: AsyncEngine = create_async_engine(
    str(settings.database_url),               # postgresql+asyncpg://...
    pool_size=settings.db_pool_size,          # 5; Neon direct tolerates this for a single API instance
    max_overflow=settings.db_max_overflow,    # 5
    pool_pre_ping=True,                        # survive Neon idle-suspend / connection recycling
    pool_recycle=300,
    connect_args={
        "statement_cache_size": 0,            # asyncpg: required when fronted by a transaction pooler
        "server_settings": {"application_name": "chronosguard-api"},
    },
)

SessionMaker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionMaker() as session:
        try:
            yield session
            await session.commit()            # transaction boundary == request lifecycle
        except Exception:
            await session.rollback()
            raise
        # session closed by context manager; connection returned to pool
```

**Transaction boundary:** one transaction per request, committed on clean handler return, rolled back on any exception (including our `AppError`s before the global handler formats them). This is essential for tenancy: `SET LOCAL app.tenant_id` is scoped to *this* transaction, so it must live and die with the request session.

**Pooler gotcha (the real one):** asyncpg auto-creates server-side prepared statements; under PgBouncer transaction-pooling (and Neon's pooled endpoint) the connection you get for the next statement may differ, causing `prepared statement "__asyncpg_*__" does not exist`. Mitigations applied: (a) point the API at Neon's **direct** endpoint and rely on SQLAlchemy's own pool, and (b) set `statement_cache_size=0` so we are safe even if someone flips the connection string to the pooled host. The Neon pooled endpoint is reserved for serverless/burst tooling (n8n), not the API.

`expire_on_commit=False` so returned ORM objects remain usable for response serialization after the commit.

---

## 3. The tenancy mechanism, end-to-end

**Flow:** `X-API-Key` header → hash → `ApiKey` row → `tenant_id` + scopes → open session → `SET LOCAL app.tenant_id` + `SET LOCAL ROLE` → handler queries → RLS filters every tenant-scoped row.

### 3a. DB-side (migration, raw SQL)

```sql
-- App connects as a NON-superuser role so RLS is actually enforced (superusers bypass RLS).
-- Tenant-scoped tables only. regulatory_documents/_chunks have NO RLS (global corpus).
ALTER TABLE org_policies   ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_runs     ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_findings ENABLE ROW LEVEL SECURITY;
ALTER TABLE org_policies   FORCE ROW LEVEL SECURITY;   -- enforce even for table owner

CREATE POLICY tenant_isolation ON org_policies
  USING       (tenant_id = current_setting('app.tenant_id', true)::uuid)
  WITH CHECK  (tenant_id = current_setting('app.tenant_id', true)::uuid);
-- (identical policy on audit_runs, audit_findings)
```

`current_setting('app.tenant_id', true)` returns NULL (not an error) when unset → predicate is false → zero rows. A missing tenant context can never leak data; it fails closed.

### 3b. App-side dependency (composes with `get_session`)

`core/security.py` + `core/tenancy.py`:

```python
from fastapi import Depends, Header
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from chronosguard.core.db import get_session
from chronosguard.core.errors import Unauthorized, Forbidden

class Principal(BaseModel):
    tenant_id: UUID
    api_key_id: UUID
    scopes: frozenset[str]

async def authenticate(
    x_api_key: str = Header(..., alias="X-API-Key"),
    session: AsyncSession = Depends(get_session),
) -> Principal:
    prefix, _, _ = x_api_key.partition(".")            # "cgk_live_ab12" lookup, then constant-time verify
    row = await lookup_api_key_by_prefix(session, prefix)
    if row is None or not verify_key(x_api_key, row.key_hash) or row.revoked_at is not None:
        raise Unauthorized("Invalid or revoked API key")
    return Principal(tenant_id=row.tenant_id, api_key_id=row.id, scopes=frozenset(row.scopes))

async def tenant_session(
    principal: Principal = Depends(authenticate),
    session: AsyncSession = Depends(get_session),     # SAME cached session instance per request
) -> AsyncSession:
    # SET LOCAL is transaction-scoped → tied to this request's txn, auto-reset on commit/rollback.
    # Parameterized via set_config to prevent any injection through the (already-trusted) uuid.
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(principal.tenant_id)},
    )
    return session

def require_scope(*needed: str):
    async def _guard(principal: Principal = Depends(authenticate)) -> Principal:
        if not set(needed) & principal.scopes and "admin" not in principal.scopes:
            raise Forbidden(f"Requires scope: {needed}")
        return principal
    return _guard
```

FastAPI caches a dependency result within a request, so `Depends(get_session)` resolves to **one** `AsyncSession`; `authenticate` and `tenant_session` both receive it, guaranteeing `SET LOCAL` runs on the exact connection/transaction the handler then uses. Handlers depend on `tenant_session` (gets isolation) + `require_scope(...)` (gets authz). Global-corpus routes depend only on `authenticate` (no tenant context needed).

**Test that must exist:** `test_tenancy_rls.py` seeds tenant A + B, writes a policy as A, then queries as B and asserts zero rows — and asserts that bypassing `tenant_session` (no `SET LOCAL`) also returns zero, proving fail-closed.

---

## 4. AuthN / AuthZ

**Decision: org-scoped API keys only. User-level auth DEFERRED (post-MVP)** — the consumers are machines (n8n) and a single-org dashboard; per-user identity adds login/session/refresh machinery that buys nothing for the MVP audit loop.

**Key format:** `cgk_{env}_{prefix8}.{secret32}` (e.g. `cgk_live_ab12cd34.<32-byte-urlsafe>`).
- Stored: `prefix` (indexed, plaintext, for O(1) lookup) + `key_hash` (SHA-256 of full key; keys are high-entropy random so a fast hash is fine — bcrypt/argon2 is for low-entropy human passwords and would only add latency here). Verify with `hmac.compare_digest`.
- Plaintext shown **once** at creation, never stored.

```text
ApiKey: id(uuid) · tenant_id(fk) · prefix(unique idx) · key_hash · scopes(text[])
        · name · created_at · last_used_at · revoked_at(nullable) · expires_at(nullable)
```

**Scopes:** `read` (browse corpus, read policies/audits), `audit` (create audit runs, CRUD policies), `admin` (trigger ingestion, manage keys). `admin` implies all.

**Rotation stance:** create-new + revoke-old (overlap window supported by allowing N active keys per tenant). No automatic rotation at MVP; `expires_at` field exists but enforcement is **DEFERRED**.

---

## 5. Endpoint inventory — Phase 1

Base: `/api/v1`. All non-health routes require `X-API-Key`. Errors are `application/problem+json`.

### Health
| Method | Path | Auth | Req | Resp | Notes |
|---|---|---|---|---|---|
| GET | `/healthz` | none | – | `{"status":"ok"}` | liveness; no DB |
| GET | `/readyz` | none | – | `HealthStatus` | checks DB `SELECT 1` + pgvector + OpenAI key presence; 503 if degraded |

### Audit (the core loop — 202 + poll)
| Method | Path | Auth/scope | Req | Resp | Notes |
|---|---|---|---|---|---|
| POST | `/audits` | `audit` | `AuditCreate` | **202** `AuditRun` | `Idempotency-Key` header honored; returns existing run on replay |
| GET | `/audits/{run_id}` | `read` | – | `AuditRun` | status: `queued/running/succeeded/failed`; tenant-scoped via RLS |
| GET | `/audits` | `read` | cursor params | `Page[AuditRunSummary]` | keyset by `created_at,id` desc |
| GET | `/audits/{run_id}/findings` | `read` | cursor params | `Page[AuditFinding]` | the diff/citation payload for UI |

`AuditCreate`:
```python
class AuditCreate(BaseModel):
    policy_id: UUID | None = None          # audit a stored policy...
    policy_text: str | None = None          # ...or ad-hoc text (mutually exclusive)
    jurisdiction: str = Field(examples=["PK", "US-TX"])
    as_of_date: date | None = None          # temporal anchor; default = today (server UTC)
    model_config = ConfigDict(json_schema_extra={"example": {
        "policy_id": "0193...", "jurisdiction": "PK", "as_of_date": "2026-06-06"}})
```
`AuditRun` (response):
```python
class AuditRun(BaseModel):
    id: UUID; status: AuditStatus; jurisdiction: str; as_of_date: date
    created_at: datetime; finished_at: datetime | None
    is_compliant: bool | None                # null until succeeded
    finding_count: int | None
    error: ProblemDetail | None              # populated on failed
```
`AuditFinding` carries the diff + citation contract the Next.js UI traces:
```python
class AuditFinding(BaseModel):
    id: UUID; risk_level: Literal["HIGH","MEDIUM","LOW"]
    offending_policy_text: str; legal_rule_text: str
    citation: str; suggested_fix: str
    document_id: int; chunk_id: int; source_url: str   # deep-link for citation tracing
    effective_date: date; expiration_date: date | None
```

### Policies (tenant-scoped CRUD)
| Method | Path | Scope | Req | Resp |
|---|---|---|---|---|
| POST | `/policies` | `audit` | `PolicyCreate` | **201** `Policy` |
| GET | `/policies` | `read` | cursor | `Page[PolicySummary]` |
| GET | `/policies/{id}` | `read` | – | `Policy` |
| PATCH | `/policies/{id}` | `audit` | `PolicyUpdate` | `Policy` |
| DELETE | `/policies/{id}` | `audit` | – | **204** |

### Regulatory corpus (global, read-only to tenants)
| Method | Path | Scope | Req | Resp | Notes |
|---|---|---|---|---|---|
| GET | `/regulatory/documents` | `read` | filters + cursor | `Page[DocumentSummary]` | filter `issuing_body`, `document_type`, `jurisdiction` |
| GET | `/regulatory/documents/{id}` | `read` | – | `DocumentDetail` | metadata + chunk count |
| GET | `/regulatory/documents/{id}/chunks` | `read` | cursor | `Page[ChunkDetail]` | citation tracing: ordered by `legal_citation` |
| POST | `/regulatory/search` | `read` | `RegSearch` | `Page[ChunkHit]` | temporal+vector semantic search (no LLM); powers UI explore + debugging retrieval |

`RegSearch`: `{ query: str, jurisdiction: str, as_of_date: date|None, top_k: int=10 }` → returns chunks with `score`, applying the same temporal filter as audit (effective ≤ as_of < expiration, `is_active`).

### Admin / ingestion (the n8n contract)
| Method | Path | Scope | Req | Resp | Notes |
|---|---|---|---|---|---|
| POST | `/admin/ingest` | `admin` | `IngestRequest` | **202** `IngestJob` | `Idempotency-Key` keyed on `source_url`; n8n nightly poller calls this |
| GET | `/admin/ingest/{job_id}` | `admin` | – | `IngestJob` | status poll |

`IngestRequest`:
```python
class IngestRequest(BaseModel):
    source_url: HttpUrl
    issuing_body: str; document_type: str
    jurisdiction: str
    published_date: date
    effective_date: date
    expiration_date: date | None = None
    supersedes_document_id: int | None = None   # marks prior doc's chunks is_active=False
```
Ingestion (download→parse→chunk→embed→upsert) runs as a background job identical to audit's pattern; the route returns 202. n8n only needs: POST to enqueue, GET to confirm, `X-API-Key` with `admin` scope.

---

## 6. Long-running audit handling

**Decision: 202 + polling.** SSE and websockets are rejected for MVP — PaaS proxies (Render/Fly) and n8n don't need streaming, and polling is trivially testable.

**Execution (MVP):** an in-process background runner using FastAPI `BackgroundTasks`/an `asyncio.TaskGroup` started in `main.py` lifespan, draining a DB-backed queue (`audit_runs.status='queued'`). The `audit_runs` row **is** the job record — no Redis, no Celery.

```text
POST /audits → insert AuditRun(status=queued) → return 202 + Location: /api/v1/audits/{id}
runner: claim queued row (UPDATE ... SET status='running' ... WHERE status='queued'
        RETURNING ... with FOR UPDATE SKIP LOCKED)  ← safe if we scale to 2 instances
      → retrieval_service → provider.chat (Structured Outputs) → insert findings
      → status='succeeded' | 'failed' (+ problem detail)
client polls GET /audits/{id} until terminal
```

**Upgrade path (DEFERRED):** when audit volume or a multi-instance deploy demands it, swap the in-process drainer for an external worker process reading the same `audit_runs` table (`FOR UPDATE SKIP LOCKED` already makes this safe) — no schema or API change. A managed queue (e.g. Neon/PG-backed `pgmq`, or Redis) is the next rung, still behind the same 202 contract.

**Sync escape hatch:** `POST /audits?wait=true` (capped, e.g. ≤4k chars, single jurisdiction) awaits the result inline up to a 25s budget, else falls back to 202 semantics. Convenience for the dashboard's "quick check"; not the primary path.

---

## 7. Error taxonomy (RFC 9457)

`core/errors.py`:

```python
class AppError(Exception):
    status: int = 500
    type_: str = "about:blank"     # stable URN slug, e.g. "urn:chronosguard:error:not-found"
    title: str = "Internal Server Error"
    def __init__(self, detail: str | None = None, **ext): ...

class Unauthorized(AppError):    status, title = 401, "Unauthorized"
class Forbidden(AppError):       status, title = 403, "Forbidden"
class NotFound(AppError):        status, title = 404, "Not Found"
class Conflict(AppError):        status, title = 409, "Conflict"            # idempotency replay mismatch
class UnprocessablePolicy(AppError): status, title = 422, "Unprocessable"
class ProviderError(AppError):   status, title = 502, "Upstream AI Error"  # OpenAI failure
class RateLimited(AppError):     status, title = 429, "Too Many Requests"
```

`ProblemDetail` response model (also surfaced in OpenAPI as the error schema):
```python
class ProblemDetail(BaseModel):
    type: str; title: str; status: int
    detail: str | None = None
    instance: str | None = None        # request path
    request_id: str                    # correlate with logs
    errors: list[FieldError] | None = None   # validation field map
```

**Global handlers** (registered in `main.py`):
- `AppError` → serialize to `ProblemDetail`, content-type `application/problem+json`, status from class.
- `RequestValidationError` (Pydantic/FastAPI 422) → reshape into `ProblemDetail` with `errors[]` (`{loc, msg, type}`), title `"Validation Error"`.
- `IntegrityError`/DB → map unique-violation to `Conflict`, else generic 500.
- Catch-all `Exception` → 500 ProblemDetail with **no internal detail leaked** (generic title), full stack logged with `request_id`.

**Log vs return:** Always log `request_id`, `tenant_id`, `api_key_id`, path, status, latency, `error.type`. Return to client: title/detail/type/status/request_id + validation field errors. Never return stack traces, SQL, or OpenAI raw errors (wrapped as generic `ProviderError`). `request_id` is the bridge — set by middleware, bound into structlog contextvars, echoed in every response.

---

## 8. Cross-cutting API conventions

**Versioning:** `/api/v1` path prefix on all business routes; health endpoints unversioned. Breaking changes → `/api/v2` mounted alongside.

**Pagination — keyset/cursor (decided):**
```python
class CursorParams(BaseModel):
    cursor: str | None = None          # opaque base64 of (sort_value, id)
    limit: int = Field(20, ge=1, le=100)

class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None            # null = last page
```
Keyset over offset because the regulatory corpus and audit findings grow under concurrent ingestion; offset double-counts/skips rows. Cursor encodes the last row's `(ordered_column, id)`; query does `WHERE (col, id) < (:c, :id) ORDER BY col DESC, id DESC LIMIT :n+1`.

**Idempotency (audit + ingest creation):** client sends `Idempotency-Key` header (UUID/ULID). We store `(tenant_id, idempotency_key) → audit_run_id` unique. Replay with same key + same body → return the original run (200, not a new 202). Same key + different body → `409 Conflict`. n8n's at-least-once retries thus never create duplicate ingests/audits.

**Rate limiting:** **DEFERRED for MVP.** Stance: rely on PaaS-edge limits initially; add `slowapi` (in-memory per-API-key token bucket) as the first in-app rung when needed. Documented so it isn't forgotten, not built now.

---

## 9. OpenAPI hygiene (the Next.js client contract)

- **`operation_id`** explicitly set per route (e.g. `create_audit`, `get_audit`, `list_audit_findings`, `search_regulatory`) → `openapi-typescript` / `orval` generate clean method names instead of `..._api_v1_audits_post`.
- **Tags:** `health`, `audits`, `policies`, `regulatory`, `admin` → grouped SDK + docs.
- **Response models on every route**, including the **`responses=` map for 401/403/404/409/422 → `ProblemDetail`** so the generated client has typed errors.
- **Examples** via `json_schema_extra` on request/response schemas (shown above) so the UI team sees real payloads.
- `servers` set per env; `summary`/`description` from docstrings.
- Spec committed to repo (`openapi.json` exported in CI) so the frontend regenerates its typed client deterministically and PRs show contract diffs.

---

## Open risks in my domain

- **Neon idle-suspend cold starts:** the direct endpoint can suspend; `pool_pre_ping`+`pool_recycle` mask most cases, but first request after suspend may spike latency or transiently fail — needs a retry-on-connect wrapper if it bites in practice.
- **In-process audit runner dies with the instance:** a queued/running audit on a crashed/redeployed PaaS dyno is orphaned. Mitigation needed: a startup reaper that resets stale `running` rows (claimed > N min ago) back to `queued`. Designed-for but not free.
- **`SET LOCAL` correctness hinges on the single-session-per-request invariant:** any future code that opens a second session, uses `BackgroundTasks` touching tenant tables without re-setting context, or runs the audit worker without `SET LOCAL` will silently lose isolation (fails *closed* to empty results, but still a bug). Must be guarded by the RLS test suite, not convention.
- **Non-superuser app role required for RLS to bind:** if the deployment connection string uses the Neon owner/superuser role, `FORCE ROW LEVEL SECURITY` is the only thing saving us on owned tables, and policies are bypassed elsewhere. Provisioning a dedicated least-privilege role on Neon is a setup step that's easy to skip.
- **Idempotency on ingestion keyed to `source_url`** assumes a gazette URL is immutable; if regulators re-publish a corrected PDF at the same URL, the dedupe will suppress a legitimate re-ingest. May need a content-hash component to the key.