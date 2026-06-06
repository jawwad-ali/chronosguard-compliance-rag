# ChronosGuard Compliance — Production Architecture

**Temporal Compliance RAG Engine — Backend MVP Blueprint (v1.0)**

> Synthesized from a 5-domain parallel design (data, RAG, API, ingestion, ops) reviewed by 3
> adversarial critics (overengineering, cross-domain consistency, completeness/risk). Raw design
> material lives in `.design/`. This document is the single source of truth; where it conflicts
> with `project-document.md`, this document wins (deviations are recorded in §12).

---

## 0. Locked decisions

| # | Decision | Choice |
|---|---|---|
| 1 | Tenancy | Single Postgres, shared schema, `tenant_id` + **Row-Level Security**. Regulatory corpus is GLOBAL; org policies / audit runs / findings are tenant-scoped. |
| 2 | AI stack | All OpenAI: `text-embedding-3-small` (1536-dim) + a small GPT tier model via **Structured Outputs** for audit verdicts. Model IDs are config, never hardcoded. |
| 3 | Scope | Backend core first. Next.js UI and n8n automation are **contracts only** in Phase 1. |
| 4 | Deployment | Managed PaaS: **Neon** (Postgres + pgvector) + **Render** (API). Local dev: Docker Compose Postgres only, API runs natively via `uv`. |

**Right-sizing rule applied throughout:** production-grade ≠ enterprise cosplay. Every deferred
item is listed in §11 with its re-activation trigger.

---

## 1. System overview

```text
                      ┌─────────────────────────────────────────────┐
                      │  Render (single service, MVP)               │
  n8n (Phase 2) ───▶  │  ┌───────────────┐   ┌──────────────────┐   │
  POST /admin/ingest  │  │ FastAPI       │   │ In-process worker │   │
                      │  │ /api/v1/*     │   │ (asyncio drainer) │   │
  Next.js (Phase 2)─▶ │  │ role: cg_app  │   │ role: cg_worker   │   │
  202 + poll          │  └──────┬────────┘   └──────┬───────────┘   │
                      └─────────┼───────────────────┼───────────────┘
                                │ RLS-bound          │ corpus writes +
                                ▼                    ▼ per-job tenant ctx
                      ┌─────────────────────────────────────────────┐
                      │  Neon Postgres + pgvector                   │
                      │  GLOBAL: regulatory_documents/chunks,       │
                      │          supersessions, jurisdictions, jobs │
                      │  TENANT (RLS): organizations, org_policies, │
                      │          org_policy_versions, audit_runs,   │
                      │          audit_findings                     │
                      └─────────────────────────────────────────────┘
                                          │
                                          ▼
                                   OpenAI API
                          (embeddings + structured verdicts)
```

**Core loop:** tenant submits policy text + jurisdiction + as-of date → policy is split into
clauses → each clause is embedded and matched against the **temporally filtered** regulatory
corpus → a structured-output LLM call judges each clause against only the retrieved excerpts →
quote-grounding verification kills hallucinated findings → tri-state verdict + cited findings.

---

## 2. Foundational conventions

| Concern | Decision | Rationale |
|---|---|---|
| Primary keys | `BIGINT GENERATED ALWAYS AS IDENTITY`, **exposed directly in the API** | Single-writer system; narrow FKs; consumers are trusted machine clients behind API keys. Opaque `public_id` is DEFERRED (§11). |
| Timestamps | `TIMESTAMPTZ NOT NULL DEFAULT now()`, server-side; `updated_at` via one trigger | App clocks drift; a temporal product trusts the DB clock. No `datetime.utcnow()` anywhere. |
| Legal effectivity | **`DATE`**, not timestamp — `effective_date`, `expiration_date`, `as_of_date` | "In force on 1 July 2026" is a calendar question. `DATE` end-to-end kills tz-boundary bugs. `as_of` resolves to a `date` at the API boundary. |
| Soft delete | Only `organizations` and `org_policies` carry `deleted_at`. Audit runs/findings are append-only. Regulatory data is never deleted — only temporally retired. | Evidence record + temporal model; no global soft-delete framework. |
| Python | 3.12, `uv`, ruff (`E F I UP B SIM ASYNC S RUF`), **mypy strict from day 1** | Cheap on greenfield, brutal to retrofit. |
| Naming | Alembic naming convention pinned on metadata before migration 0001 | Deterministic constraint names; reversible migrations. |

---

## 3. Data architecture

### 3.1 Table inventory

**Global (no RLS; written by `cg_worker`, read by everyone):**

| Table | Purpose |
|---|---|
| `jurisdictions` | Reference: `code` (PK, e.g. `PK`, `US-TX`, `EU`), `name`, `parent_code` |
| `regulatory_documents` | Gazette/SRO/circular metadata + ingestion provenance |
| `regulatory_chunks` | Hierarchical chunks + vector + temporal columns |
| `supersessions` | Lineage edges: chunk A amended/repealed/replaced by chunk B |
| `jobs` | **The single durable queue** for both audit and ingest work |
| `api_keys` | Auth principals. **Deliberately NOT RLS-protected** — it is the auth bootstrap table (lookup must work before tenant context exists). Stores only hashes. |

**Tenant-scoped (RLS-enforced):**

| Table | Purpose |
|---|---|
| `organizations` | Tenant root; `tenant_id == organizations.id` |
| `org_policies` | Logical policy document (pointer to current version) |
| `org_policy_versions` | Immutable versioned policy text |
| `audit_runs` | One audit execution: snapshot of inputs, verdict, coverage, cost |
| `audit_findings` | Individual violations with citation traceability |

### 3.2 Core schema (canonical — single authorship)

```python
class RegulatoryDocument(SQLModel, table=True):
    __tablename__ = "regulatory_documents"
    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(index=True)
    issuing_body: str = Field(index=True)          # SECP, SBP
    document_type: str = Field(index=True)         # SRO, Circular, Gazette, Notification
    jurisdiction: str = Field(foreign_key="jurisdictions.code", index=True)
    language: str = Field(default="en")            # script-detected at ingest; non-en → review
    source_url: str
    source_etag: str | None = None                 # latency optimization ONLY, never correctness
    content_hash: str                              # sha256(extracted markdown)
    version: int = Field(default=1)                # corrected re-publish ⇒ new row, version+1
    published_date: dt.date
    extraction_status: str = Field(default="pending")  # pending | review | confirmed
    review_reason: str | None = None               # scanned_pdf | non_english | low_confidence | injection_flag | no_structure
    raw_markdown: str | None = None                # kept for re-chunk/re-embed
    ingested_at: dt.datetime                       # server_default now()
    # UNIQUE (source_url, content_hash)  ← idempotency: same content twice at one URL = no-op;
    #                                       new content at same URL = new version row

class RegulatoryChunk(SQLModel, table=True):
    __tablename__ = "regulatory_chunks"
    id: int | None = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="regulatory_documents.id", index=True)
    chunk_index: int                               # order within document
    content: str                                   # raw clause text (no breadcrumb)
    embed_text_hash: str                           # sha256 of what was embedded
    legal_citation: str                            # "Section 12-B(4)(a)"
    heading_path: str                              # "Part II > Chapter 3 > Section 12-B"
    jurisdiction: str = Field(foreign_key="jurisdictions.code", index=True)
    effective_date: dt.date = Field(index=True)
    effective_date_source: str                     # extracted | defaulted_to_published | operator_confirmed
    expiration_date: dt.date | None = Field(default=None, index=True)
    token_count: int
    embedding_model: str                           # stamped per chunk
    embedded_at: dt.datetime | None = None         # NULL ⇒ pending embedding (resumability)
    embedding: list[float] | None = Field(
        default=None, sa_column=Column(Vector(1536)))   # NULLABLE: chunks persist before embeddings

class Supersession(SQLModel, table=True):
    __tablename__ = "supersessions"
    id: int | None = Field(default=None, primary_key=True)
    superseded_chunk_id: int = Field(foreign_key="regulatory_chunks.id", index=True)
    superseding_chunk_id: int | None = Field(default=None, foreign_key="regulatory_chunks.id")  # NULL = repeal
    relation: str                                  # amends | repeals | replaces
    supersession_effective_date: dt.date
    note: str | None = None
```

**`is_active` does not exist.** It was the #1 cross-domain bug in design review (three domains
disagreed on whether it was authoritative, derived, or dropped). In-force status is **always
derived from dates** relative to the as-of date. No stored boolean to go stale.

### 3.3 The temporal model (the product's moat)

**Pragmatic uni-temporal valid-time.** Full bitemporality is DEFERRED (§11).

- A chunk is in force on date `d` iff `effective_date <= d AND (expiration_date IS NULL OR d < expiration_date)` — half-open interval `[effective, expiration)`.
- **Supersession = atomically closing the interval + recording lineage.** When an operator
  confirms "Circular 12/2026 supersedes Circular 5/2019", one transaction: (a) sets the old
  chunks' `expiration_date = new.effective_date`, (b) inserts `supersessions` edges.
  **`expiration_date` is the sole retrieval authority; the `supersessions` table is lineage
  metadata for the diff UI and staleness detection — it is never in the hot query path.**
  (Resolves the three-way supersession contradiction: one mechanism filters, one mechanism explains.)
- **Retroactive amendments** are honest: a rule passed in Sept legally effective 1 Jan gets
  `effective_date = Jan 1` (valid time) while `ingested_at` records Sept (system time). An as-of
  March query run today correctly returns the retroactive rule.
- **Staleness flagging:** when a supersession's `supersession_effective_date < today`, ingestion
  confirm runs one query marking affected `audit_runs` (`as_of_date >= that date` AND retrieved a
  now-expired chunk) as `stale = true`. Verdicts never silently rot — the API surfaces
  "re-run recommended". We flag, never auto-rerun.

**The canonical predicate lives in exactly ONE module** (`retrieval/temporal.py`) and every
consumer — audit retrieval, `/regulatory/search`, the eval harness — imports it. There is no
second copy anywhere:

```python
def as_of_predicate(jurisdiction: str, as_of: dt.date):
    """Chunks in force in `jurisdiction` on `as_of`. THE temporal authority."""
    return (
        (RegulatoryChunk.jurisdiction == jurisdiction)
        & (RegulatoryChunk.effective_date <= as_of)
        & (RegulatoryChunk.expiration_date.is_(None) | (RegulatoryChunk.expiration_date > as_of))
        & (RegulatoryChunk.embedding.is_not(None))
        & (RegulatoryDocument.extraction_status == "confirmed")   # review-gate: unconfirmed law NEVER audits
    )
```

This predicate gets exhaustive table-driven unit tests (boundary dates, exactly-on-effective,
exactly-on-expiration, superseded, retroactive, unconfirmed) — it is the most-tested code in the repo.

### 3.4 Vector strategy

| Decision | Value | Rationale |
|---|---|---|
| Type | plain `vector(1536)`, nullable | `halfvec` cut by review: unproven recall risk on legal text traded for storage savings we don't need at <100k chunks. Trigger to revisit: ~1M chunks. |
| Index | **One** HNSW over all rows: `USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64) WHERE embedding IS NOT NULL` | Per-jurisdiction partial indexes cut by review: with one live jurisdiction it's pure ceremony. HNSW > IVFFlat: no training step, tolerates incremental growth. |
| Distance | cosine (`<=>`) | Matches OpenAI embeddings. |
| Query tuning | default `ef_search`; `hnsw.iterative_scan` OFF until the eval harness shows filter starvation | Don't pay latency insurance against an unmeasured problem. One-line GUC to flip. |
| Bulk loads | load rows first, `CREATE INDEX` after; high `maintenance_work_mem` for build sessions | HNSW build is memory-bound; post-load build is far faster. |

The spec's "Multi-Tenant Vector Partitioning" is, concretely: a **global shared corpus** (nothing
tenant-specific to partition), **temporal+jurisdiction filtered ANN**, with tenant isolation
applying only to the policy/audit side (no vectors there in MVP).

### 3.5 RLS design

**Role model (3 roles, 2 at runtime):**

| Role | Used by | Powers |
|---|---|---|
| `cg_owner` | Migrations only (Alembic, CI) | Owns all tables. Never a runtime credential. |
| `cg_app` | API request path | No `BYPASSRLS`, **not table owner** (owners bypass RLS — this is the crux). `SELECT` on global tables; `SELECT/INSERT/UPDATE` on tenant tables (no `DELETE` on append-only `audit_runs`/`audit_findings`); `SELECT/INSERT` on `jobs`; `SELECT` + `UPDATE(last_used_at)` on `api_keys`. |
| `cg_worker` | In-process worker + ingestion CLI | Full CRUD on `jobs`; write on global corpus tables; tenant-table writes still RLS-bound (worker sets per-job tenant context). |

**Policies (migration DDL, hand-written `op.execute`):**

```sql
CREATE FUNCTION app_current_tenant() RETURNS bigint
LANGUAGE sql STABLE AS $$
  SELECT NULLIF(current_setting('app.tenant_id', true), '')::bigint
$$;
-- NULLIF guard: empty-string AND unset both yield NULL → predicate UNKNOWN → zero rows.
-- Fail-closed by construction. This function is the ONLY place the GUC is read.

ALTER TABLE org_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE org_policies FORCE  ROW LEVEL SECURITY;   -- binds even the table owner
CREATE POLICY tenant_isolation ON org_policies
  USING      (tenant_id = app_current_tenant())
  WITH CHECK (tenant_id = app_current_tenant());
-- identical on: org_policy_versions, audit_runs, audit_findings
-- organizations: USING (id = app_current_tenant())
```

**Context setting — transaction-local, always:**

```python
await session.execute(
    text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
)  # is_local=true ⇒ scoped to THIS transaction. A session-scoped GUC on a pooled
   # connection would leak the previous request's tenant — the classic RLS bug.
```

- **Request path:** FastAPI dependency chain `authenticate → tenant_session`. Dependency caching
  guarantees one `AsyncSession` per request; `SET LOCAL` runs on the exact connection the handler
  uses. Transaction boundary == request.
- **Worker path:** the worker claims a job from the global `jobs` table (no RLS — this is *why*
  the queue is global: a tenant-scoped queue would be invisible to the worker), reads
  `job.tenant_id`, then opens a fresh transaction and sets context before any tenant-scoped work.
  Design review proved the original worker design **could not INSERT findings at all** under
  `WITH CHECK` — the global-queue + per-job-context pattern is the fix.
- **Mandatory CI gates:** cross-tenant SELECT isolation, `WITH CHECK` INSERT rejection,
  no-context-set returns zero rows (fail-closed), **and the worker-path INSERT test** —
  all under a non-superuser test role, all blocking.

### 3.6 Jobs — one queue, one worker

Design review collapsed two independently-invented queue implementations into one:

```sql
CREATE TABLE jobs (
  id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind         TEXT NOT NULL,                  -- 'audit' | 'ingest'
  ref_id       BIGINT,                         -- audit_runs.id | regulatory_documents.id
  tenant_id    BIGINT,                         -- set for audit jobs; NULL for ingest
  status       TEXT NOT NULL DEFAULT 'queued', -- queued | running | succeeded | failed
  payload      JSONB NOT NULL DEFAULT '{}',
  attempts     INT NOT NULL DEFAULT 0,
  max_attempts INT NOT NULL DEFAULT 3,
  error        TEXT,
  locked_at    TIMESTAMPTZ,                    -- lease
  locked_by    TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_jobs_claim ON jobs (status, created_at) WHERE status = 'queued';
```

- **Claim:** `UPDATE jobs SET status='running', locked_at=now(), locked_by=:worker
  WHERE id = (SELECT id FROM jobs WHERE status='queued' ORDER BY created_at
  FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *` — safe for N workers without changes.
- **Reaper:** on worker startup + every 5 min: `running AND locked_at < now() - interval '15 min'`
  → back to `queued` (attempts+1) or `failed` if exhausted. ~10 lines that kill a whole class of
  stuck-job incidents.
- **Execution (MVP):** an `asyncio` task started in the FastAPI lifespan drains the queue
  in-process (one Render service, no extra cost). Granular phase tracking
  (`fetching/parsing/embedding`) is **logged, not persisted** — observability theater cut.
- **Upgrade path:** a separate worker process reading the same table (zero schema/API change),
  then arq+Redis if pickup latency ever matters.

---

## 4. Retrieval & audit pipeline

### 4.1 Pipeline

```text
policy text ──▶ split into clauses ──▶ embed (one batched call) ──▶ per clause:
   SQL candidate filter (as_of_predicate) + ANN top-24 ──▶ trim to top-8 (soft threshold)
   + exact-citation regex lookup (ILIKE legal_citation) merged in
──▶ context assembly (JSON excerpt array, ref_id keyed, ≤6k tokens)
──▶ GPT Structured Outputs verdict (strict schema, temperature 0)
──▶ quote-grounding verification (hard gate)
──▶ run-level rollup: tri-state verdict + coverage counts
```

- **Unit of audit = the clause.** Deterministic splitter (blank lines / headings / numbered items;
  merge runts <120 chars; cap ~1500 chars). Clause array is snapshotted as JSONB on `audit_runs`
  for replay. Clauses audited concurrently, `asyncio.Semaphore(5)`.
- **k=8 per clause** from ANN top-24; soft distance threshold 0.55 — but always pass the best
  surviving candidate flagged `weak_match` rather than retrieving nothing. Threshold is an
  eval-tuned knob.
- **Hybrid search:** vector + a deterministic citation-regex exact lookup. Postgres FTS/RRF is
  DEFERRED behind the already-abstracted `merge_candidates()` seam.
- **Zero candidates ⇒ `INSUFFICIENT_EVIDENCE`, never "compliant".** The spec's
  `return AuditResponse(is_compliant=True)` on empty retrieval is a correctness bug, overridden.
  A false green check is the worst failure mode a compliance tool has.

### 4.2 Verdict contract (tri-state, run-level coverage)

```python
class ClauseVerdict(BaseModel):            # per-clause LLM output (strict Structured Outputs)
    verdict: Literal["VIOLATION", "COMPLIANT", "INSUFFICIENT_EVIDENCE"]
    findings: list[ClauseFinding]          # each: ref_id, grounding_quote, risk_level, rationale, suggested_fix
    confidence: float                      # 0..1

class AuditRunOut(BaseModel):              # run-level API response
    id: int
    status: Literal["queued", "running", "succeeded", "partial", "failed"]
    verdict: Literal["COMPLIANT", "VIOLATIONS_FOUND", "INSUFFICIENT_EVIDENCE"] | None
    coverage: Coverage                     # counts: {violation, compliant, insufficient_evidence, error}
    stale: bool                            # a later retroactive amendment may invalidate this run
    jurisdiction: str
    as_of_date: dt.date
    model: str
    cost_usd: float | None
    ...
```

Rollup rules (no bare boolean anywhere):
- `verdict = COMPLIANT` **only if** ≥1 clause was evaluated against real retrieved law AND zero
  violations AND zero errored clauses.
- Any errored clause ⇒ `status = partial`, `verdict` ≠ COMPLIANT.
- All clauses insufficient ⇒ `verdict = INSUFFICIENT_EVIDENCE` (the UI renders "no governing law
  found", never a green check).

### 4.3 Hallucination defenses (all server-side)

1. **Quote-grounding hard gate:** every finding's `grounding_quote` must occur in the cited
   excerpt (normalized substring; rapidfuzz ≥0.92 fallback). Not found ⇒ finding dropped, clause
   downgraded. Grounding pass-rate is logged as the hallucination canary.
2. **`citation` / `source_url` / `legal_rule_text` come from the DB by `ref_id` join — never from
   the LLM.** Fabricated citations are structurally impossible.
3. **Prompt-injection containment** (ingested gazettes are untrusted input):
   excerpts enter the prompt as a **structured JSON array** keyed by `ref_id` — not inline
   prose tags a crafted chunk could forge (`</ref_id>` injection). Chunk content is sanitized of
   delimiter-lookalike tokens at assembly. Ingest-time pattern flagging (`ignore previous
   instructions…`) **quarantines** the chunk to the review queue (not just a warning). The audit
   model has no tools and must return the fixed schema — no action channel.
4. `confidence` + `weak_match` combine into a `needs_review` flag on findings. Low-confidence
   violations are flagged, never suppressed.

### 4.4 OpenAI usage

| Concern | Decision |
|---|---|
| Models | `OPENAI_EMBED_MODEL` (default `text-embedding-3-small`) and `OPENAI_AUDIT_MODEL` (small GPT tier; **config-driven, validated at startup** — exact ID pinned at implementation kickoff against the current OpenAI lineup, with an escalation hook for `HIGH`-risk clauses deferred). |
| Determinism | `temperature=0`, strict Structured Outputs (`strict=True`). |
| Retry | tenacity: 3 attempts, expo backoff + jitter, only on rate-limit/timeout/connection/5xx. Never on schema errors. 30s per-call timeout. |
| Partial failure | A clause that exhausts retries is `error`, never silently compliant (drives `status=partial`). |
| Degradation | `/readyz` gates audit acceptance: if OpenAI is failing, `POST /audits` returns 503 instead of accepting jobs that will dead-letter. |
| Cost telemetry | Every call logs `model, operation, prompt_tokens, completion_tokens, cost_usd, latency_ms, request_id, tenant_id`; per-run totals persisted on `audit_runs`. Day-1 requirement. |
| Budget | ~$0.001–0.003/clause at small-tier pricing ⇒ a 40-clause policy audits for pennies. |

### 4.5 Streaming

**Complete JSON, 202 + poll. No SSE, no `?wait=true` sync path.** The spec's `StreamingResponse`
aspiration is overridden: structured verdicts need the complete object for validation + grounding;
a sync escape hatch doubles the execution surface of the riskiest code path (review finding —
cut). Per-clause SSE progress is a documented post-MVP additive.

---

## 5. API design

### 5.1 Conventions

| Concern | Decision |
|---|---|
| Versioning | `/api/v1` path prefix; health endpoints unversioned |
| Auth | `X-API-Key` header. Org-scoped keys: `cgk_{env}_{prefix8}.{secret32}`; SHA-256(key+pepper) stored, prefix-indexed lookup, constant-time verify; plaintext shown once. Scopes: `read` ⊂ `audit` ⊂ `admin`. User accounts/RBAC DEFERRED. |
| Errors | One `ProblemDetail` shape (`application/problem+json`): `{type:"about:blank", title, status, detail, instance, request_id, errors[]}`. URN type registry cut by review. Global handlers; no stack traces / SQL / raw OpenAI errors ever leak. |
| Pagination | `limit`/`offset`, cap 100, on every list. Keyset DEFERRED (trigger: any list realistically exceeds a few thousand rows). |
| Idempotency | Natural keys only: ingest dedup = `(source_url, content_hash)` at job level; duplicate audit runs are harmless appends. `Idempotency-Key` header machinery cut by review. |
| OpenAPI | Explicit `operation_id` per route; tags; `ProblemDetail` in `responses=`; examples on schemas; `openapi.json` snapshot committed + drift-tested in CI (the frozen contract for Next.js/n8n). |

### 5.2 Endpoint inventory (Phase 1)

| Method | Path | Scope | Returns | Notes |
|---|---|---|---|---|
| GET | `/healthz` | — | liveness | no dependencies |
| GET | `/readyz` | — | readiness | DB `SELECT 1` + OpenAI health; gates traffic |
| GET | `/api/v1/me` | `read` | org profile | proves auth+RLS end-to-end |
| POST | `/api/v1/audits` | `audit` | **202** AuditRun + `Location` | enqueues job |
| GET | `/api/v1/audits/{id}` | `read` | AuditRun | status/verdict/coverage/stale |
| GET | `/api/v1/audits` | `read` | Page[AuditRunSummary] | |
| GET | `/api/v1/audits/{id}/findings` | `read` | Page[Finding] | citation payload for diff UI: `chunk_id`, `document_id`, `source_url`, `legal_citation`, `effective_date`, `grounding_quote`, `needs_review` |
| POST | `/api/v1/policies` | `audit` | 201 Policy | creates v1 |
| GET/PATCH/DELETE | `/api/v1/policies/{id}` | per verb | Policy | PATCH body ⇒ new immutable version |
| GET | `/api/v1/policies` | `read` | Page[PolicySummary] | |
| GET | `/api/v1/regulatory/documents` | `read` | Page[DocSummary] | filters: body/type/jurisdiction |
| GET | `/api/v1/regulatory/documents/{id}` | `read` | DocDetail | |
| GET | `/api/v1/regulatory/documents/{id}/chunks` | `read` | Page[Chunk] | citation tracing |
| POST | `/api/v1/regulatory/search` | `read` | ranked chunks | same `as_of_predicate` as audit; powers UI explore + retrieval debugging |
| POST | `/api/v1/admin/ingest` | `admin` | **202** IngestJob | **the n8n contract** — see below |
| GET | `/api/v1/admin/ingest/{job_id}` | `admin` | IngestJob | n8n poll target — ships in MVP |

**The n8n ingest contract (settled by review):** auth is the unified **admin-scoped API key**
(no separate static-token scheme — one credential model, per-key revocation + log attribution).
The body carries **hints only**:

```jsonc
{
  "source_url": "https://www.secp.gov.pk/.../circular-12-2026.pdf",
  "issuing_body": "SECP",            // hint
  "jurisdiction": "PK",              // hint
  "document_type": "Circular",       // hint
  "source_etag": "\"a1b2c3\""        // latency optimization only
}
```

Callers can NEVER supply `effective_date` / `expiration_date` / supersession links — legal
temporal fields are derived by extraction + verification + the review gate, or the gate is
meaningless. (`force=true` query param re-fetches ignoring ETag, for suspected silent corrections.)

### 5.3 Async session + Neon specifics

```python
engine = create_async_engine(
    settings.database_url,                  # Neon DIRECT endpoint (not pooled) for the API
    pool_size=5, max_overflow=5,
    pool_pre_ping=True, pool_recycle=300,   # survive Neon idle-suspend
    connect_args={"statement_cache_size": 0},  # asyncpg: safe even if pointed at a txn pooler
)
```

- One transaction per request; commit on clean return, rollback on exception. `expire_on_commit=False`.
- **Connection budget** asserted at startup: API pool (5+5) + worker engine (2) ≤ Neon tier limit,
  documented in `config.py`. The in-process worker shares the dyno, so idle periods let Neon
  scale to zero (cost model intact); first-query-after-suspend latency is absorbed by
  `pool_pre_ping` + one connect-retry wrapper.
- Neon **pooled** endpoint is reserved for burst tooling, never the API.

---

## 6. Ingestion pipeline

```text
job claimed ──▶ fetch (httpx, ETag fast-path) ──▶ extract (pymupdf4llm → Markdown)
  ├─ scanned? (chars/page < 100) ──▶ review: scanned_pdf      [no OCR in MVP]
  ├─ non-English script? (Unicode-range heuristic) ──▶ review: non_english
  ▼
hash + dedup (source_url, content_hash) ──▶ hierarchical chunker ──▶ metadata extraction
  (rule pre-pass + LLM Structured Outputs + evidence-substring verification)
  ├─ low confidence / no date / injection pattern ──▶ extraction_status='review' (quarantined from retrieval)
  ▼
embed (batched ≤256 inputs, resumable per-batch, embedded_at stamps) ──▶ confirm (operator) ──▶ retrievable
```

Key decisions:

- **Extractor: `pymupdf4llm`.** Pure-Python wheels (clean on Windows), fast, Markdown with
  headings/tables/reading-order. Marker (torch stack) and OCR are DEFERRED behind the
  `extract_markdown()` seam.
- **Hierarchical chunker:** regex heading detection (PART/CHAPTER/Section/(a)(i) patterns for
  SECP/SBP conventions) → heading tree → leaf chunks 300–800 tokens (merge runts, split
  over-longs on paragraphs). **Ancestor-breadcrumb prepended to embedded text**
  (`[Part II > Ch 3 > S.12-B] …`) — cheap, large recall win for legal cross-references. Fallback
  to 600-token windows when <2 headings detected, flagged `review: no_structure`.
- **Metadata extraction:** rule-based pre-pass (dates regex, issuing body from domain) feeds an
  LLM Structured Outputs call over the first ~3k tokens. **Anti-hallucination check:**
  `effective_date_evidence` must be a substring of the source. Undated docs default
  `effective_date = published_date` with `effective_date_source = 'defaulted_to_published'`
  (provenance is honest; "with immediate effect" convention = publication date, documented).
- **Review queue = `WHERE extraction_status='review'`** + CLI. No workflow engine. Unconfirmed
  documents are **excluded from retrieval by the canonical predicate** — the gate is enforced in
  the one shared filter, not by convention.
- **Supersession: operator-confirmed, machine-suggested.** LLM `supersedes_refs` + fuzzy matcher
  propose; `chronos supersede <new> --supersedes <old>` confirms — atomically closing intervals,
  inserting edges, and running the **staleness flagger** over past audit runs. Auto-linking is
  DEFERRED: a wrong link silently removes in-force law from audits.
- **Corrected re-publish (same URL, new content):** new document row `version+1`; the old
  version's chunks get expired, never mutated — last week's audit findings must remain resolvable.
- **Embedding resumability:** per-batch transactions stamping `embedded_at`; crash ⇒
  `backfill-embeddings` picks up `WHERE embedded_at IS NULL`. Never re-pay for embedded chunks.

**CLI surface (`typer`):**

```text
chronos ingest url|file <target> [--body SECP] [--jurisdiction PK] [--now]
chronos worker run-once | run-forever        # cron target / local dev
chronos status [--review] [--failed]
chronos confirm <doc_id>
chronos supersede <new_id> --supersedes <old_id> [--relation amends]
chronos reindex <doc_id>
chronos backfill-embeddings [--limit N]
chronos retry <job_id>
chronos seed                                  # dev fixtures (see §8.3)
chronos keys create --org <id> --scopes audit  # tenant provisioning
```

---

## 7. Repo layout & project structure

```text
chronosguard/
├─ apps/
│  └─ api/
│     ├─ pyproject.toml              # uv; ruff; mypy strict; pytest markers
│     ├─ alembic.ini
│     ├─ migrations/                 # env.py async; RLS/HNSW DDL as op.execute
│     ├─ src/chronosguard/
│     │  ├─ main.py                  # app factory, lifespan (worker start, reaper), handlers
│     │  ├─ core/                    # config.py, db.py, security.py, tenancy.py,
│     │  │                           # errors.py, logging.py, pagination.py
│     │  ├─ models/                  # SQLModel tables — single authorship, one import point
│     │  ├─ schemas/                 # Pydantic DTOs (API contract ≠ tables)
│     │  ├─ providers/               # base.py (EmbeddingProvider/ChatProvider Protocols,
│     │  │                           #   with .model/.dims), openai.py, fake.py (CI)
│     │  ├─ retrieval/               # temporal.py (THE predicate), candidates.py,
│     │  │                           # citations.py, policy_split.py
│     │  ├─ audit/                   # schema.py, prompt.py, grounding.py, pipeline.py, service.py
│     │  ├─ ingestion/               # fetch.py, extract.py, chunker.py, metadata.py,
│     │  │                           # supersession.py, embed.py, sanitize.py, service.py
│     │  ├─ worker/                  # runner.py (claim/lease/dispatch), reaper.py
│     │  ├─ api/v1/                  # routers: health, me, audits, policies, regulatory, admin
│     │  └─ cli/                     # typer app
│     └─ tests/
│        ├─ unit/                    # chunker, temporal truth-table, grounding, services w/ fakes
│        ├─ integration/             # real pgvector via testcontainers; migrations exercised
│        ├─ rls/                     # cross-tenant leak tests incl. WORKER write path (blocking)
│        ├─ contract/                # OpenAPI snapshot drift
│        └─ eval/                    # golden set; pytest -m eval (manual/local, real OpenAI)
├─ packages/contracts/               # openapi.json snapshot (+ generated TS types later)
├─ infra/
│  ├─ docker-compose.yml             # pgvector/pgvector:pg16 ONLY; API runs natively
│  └─ render.yaml
├─ docs/                             # ARCHITECTURE.md (this), ROADMAP.md, runbooks/
├─ .design/                          # raw parallel-design + critique artifacts (historical)
└─ .github/workflows/ci.yml
```

- Layering: `routers → services → session`. A repository module exists **only** where it earns
  its place: the temporal+vector retrieval query and the keyset-free pagination helpers. No
  blanket repository ceremony.
- Domain subpackages (`retrieval/`, `audit/`, `ingestion/`) are top-level — they are the product.
- Task runner: **poe (poethepoet)** in `pyproject.toml` — zero new binaries on Windows, recipes
  are `uv run …` wrappers (`poe up`, `poe migrate`, `poe test`, `poe seed`, `poe api`). `just` cut
  by review (new binary + shell-dialect split for pure-Python tasks).

---

## 8. Quality engineering

### 8.1 Test pyramid (shaped by what makes THIS product correct)

| Lane | Mechanics | Blocking? |
|---|---|---|
| Unit | No DB/network. Chunker golden files; **temporal predicate truth table** (the moat — exhaustive boundary dates); grounding verifier; services against `FakeProvider` (deterministic embeddings + canned verdicts). | ✅ |
| Integration | `testcontainers` `pgvector/pgvector:pg16`, same image locally and in CI. **Migrations applied from zero per run** (not `create_all`). Real cosine ordering; `EXPLAIN` asserts HNSW usage. | ✅ |
| RLS | Non-superuser test role. Tenant A/B seeds. SELECT isolation, `WITH CHECK` INSERT rejection, fail-closed-on-no-context, **worker-path INSERT under per-job context**. A cross-tenant leak is a security incident, not a flaky test. | ✅ |
| Contract | OpenAPI snapshot drift vs `packages/contracts/openapi.json`. | ✅ |
| Migration gate | Ephemeral DB: `upgrade head` from zero + `alembic check` (drift) + `downgrade -1 && upgrade head` (dev hygiene only — see rollback policy). | ✅ |
| Eval | Golden JSONL set (rules + labeled cases incl. **temporal pairs**: same policy, different as-of, different expected rule). Metrics: recall@8, MRR, verdict confusion matrix, grounding pass rate. Run **manually/locally** against real OpenAI (`pytest -m eval`). Nightly CI lane + recorded-fixture machinery DEFERRED until the set is big enough to cost real money. | ❌ informational |

Coverage: measured and reported, **not gated on a number**. The hard requirement is the existence
and passing of the `rls` + temporal lanes.

### 8.2 CI/CD (GitHub Actions → Render)

```text
PR/push: lint (ruff) ─┬─ typecheck (mypy strict) ──▶ unit ──▶ integration+rls+contract ──▶ ✓
                      └─ migration-gate (parallel)
push(main): all green ──▶ Render deploy hook ──▶ pre-deploy: alembic upgrade head ──▶ health-gated cutover
```

- Migrations are **forward-only and expand/contract** (add nullable → backfill → switch → drop
  later) so a deploy never breaks the still-running version.
- **Rollback policy (explicit):** prod rollback = **Neon PITR / branch restore + redeploy prior
  image**. `alembic downgrade` is a local-dev hygiene tool, not a prod safety net. Runbook in
  `docs/runbooks/`.
- `pip-audit` as a non-blocking advisory lane; promote when deps stabilize.

### 8.3 Seed fixtures (`chronos seed`)

Crafted to exercise every temporal edge the tests assert on:

1. SECP SRO "Funds Settlement" v1 — effective 2024-01-01, PK, "settle within **7** business days"
2. Its amendment — effective 2026-06-01, supersedes #1, "settle within **3** business days"
   (drives the spec's PocketPay demo: violation as-of June 2026, compliant as-of 2025)
3. SBP KYC directive — second issuing body, open-ended
4. An expired circular — [2020-01-01, 2022-01-01); must never surface for as_of ≥ 2022
5. A retroactive amendment — ingested "now", effective in the past (valid-time vs system-time proof)
6. Two orgs ("PocketPay", "Acme") + policies + API keys — RLS denial fixtures

CI uses the deterministic `FakeEmbeddings` provider (no OpenAI cost); local seeding can use real embeddings.

### 8.4 Observability

- **structlog**: JSON in prod, pretty console locally. ASGI middleware binds
  `request_id` + `tenant_id` into contextvars → every log line carries both, zero plumbing.
  `X-Request-ID` echoed in responses.
- **Redaction**: a processor drops/truncates `policy_text` / `content` / `embedding` values to
  `<redacted len=N sha=…>`. **Sentry `before_send` additionally scrubs exception args, `extra`,
  and SQL params with a length cap** — exceptions don't carry field names, so name-based
  redaction alone leaks (review finding).
- **Sentry: in** (free tier, ~5 lines, multi-tenant exception visibility).
- Metrics = structured-log aggregation + Sentry for MVP. Prometheus stack DEFERRED.

### 8.5 Security posture

- Secrets: Render env groups + GitHub Actions secrets. `.env` git-ignored; `.env.example` is the contract.
- API keys hashed SHA-256+pepper (high-entropy random tokens — argon2 is for human passwords).
- CORS: explicit allowlist from env; no wildcard with credentials.
- Tenant offboarding: **hard-delete admin operation** (one transaction, RLS-bypassing role,
  tombstone row recording the deletion event). Evidence immutability is overridden by customer
  deletion rights — decided now, implemented in Phase 2, documented so it's never undefined.
- Backups: Neon PITR is the backup; restore drill documented. Weekly `pg_dump` to object storage
  re-evaluated before first paying customer.

---

## 9. Environments & cost

- **Two environments: `local` and `prod`.** Staging DEFERRED — Neon branching + Render PR
  previews give ephemeral per-PR staging when wanted.
- One `Settings` class (pydantic-settings); `.env` locally, PaaS env vars in prod;
  `ENV ∈ {local, prod}` switches renderer/CORS/Sentry only.

| Item | Est. monthly (modest usage) |
|---|---|
| Neon (Launch tier: PITR + branching) | ~$19–25 |
| Render (Starter, always-on) | ~$7–25 |
| OpenAI embeddings (corpus + queries) | <$2 |
| OpenAI audit calls (~2k audits/mo) | ~$25–60 |
| Sentry | $0 |
| **Total** | **~$55–110/mo** |

---

## 10. Key risk register

| Risk | Mitigation | Status |
|---|---|---|
| Extraction fidelity on real SECP/SBP gazettes unproven | **Ingest 5–10 real gazettes before locking chunker heuristics** (Roadmap chunk 7 starts with this); review gate catches the worst | Open — highest-leverage validation |
| Urdu/bilingual gazettes (the home market!) | Script detection → `review: non_english`; explicit "English-only MVP" scoping. Never silently mis-ingest. | Scoped out, fails safe |
| Filtered-HNSW recall under tight temporal predicates | Eval harness recall gate; iterative-scan GUC ready to flip; corpus small at MVP | Monitored |
| RLS discipline (one forgotten `SET LOCAL` = silent isolation loss) | Fail-closed by construction + blocking leak tests on request AND worker paths | Engineered |
| Effective-date ambiguity ("immediate effect", phased commencement) | Provenance enum + default-to-published + review gate + `needs_review` propagation to findings | Mitigated, imperfect |
| Retroactive amendments invalidating stored verdicts | `stale` flag + flagging query at supersession confirm; never auto-rerun | Mitigated |
| Neon cold start / connection ceiling | Connection budget asserted at startup; `pool_pre_ping` + connect-retry; in-process worker preserves scale-to-zero | Engineered |
| Non-blocking lanes rot (eval, pip-audit) | Named owner ritual once team >1; revisit at Phase 2 | Accepted for MVP |

---

## 11. Deferred register (each with its re-activation trigger)

| Deferred | Trigger |
|---|---|
| `halfvec` quantization | Corpus ~1M chunks or Neon memory pressure; measure recall first |
| Per-jurisdiction partial HNSW indexes | ≥3 active jurisdictions AND measured filtered-recall degradation |
| `hnsw.iterative_scan` | Eval shows post-filter candidate starvation |
| Bitemporal "as-known-of" replay | A customer dispute requires reconstructing past system knowledge |
| Postgres FTS + RRF hybrid search | Eval shows exact-term recall gaps the citation regex misses |
| LLM reranker / model escalation for HIGH-risk clauses | Eval shows precision problems at k=8 |
| Keyset pagination | Any list realistically exceeds a few thousand rows |
| Opaque `public_id` external IDs | API exposed to untrusted public clients |
| arq + Redis worker | Sub-second job pickup or >2 concurrent workers needed |
| SSE per-clause progress | UI demand after dashboard ships |
| User accounts / RBAC | First customer with multi-user requirements |
| OCR (scanned gazettes) / Marker extractor | Scanned-PDF rejection rate becomes material |
| Urdu/bilingual ingestion | Post-MVP, explicitly scoped |
| Embedding cache for policy clauses | Re-audit volume makes embedding spend visible |
| Nightly eval CI lane + recorded fixtures | Eval set large enough to cost real money/time |
| Auto supersession linking | Confidence data from operator-confirmed history |
| Staging environment | First paying customer needing UAT |
| Rate limiting (slowapi) | First abuse signal; PaaS-edge limits until then |
| Prometheus/Grafana | Query volume justifying a metrics backend |

---

## 12. Deviations from `project-document.md` (spec corrections)

1. **`is_active` removed** — derived from dates; stored boolean is the #1 temporal staleness bug.
2. **`effective_date` is `DATE`, not `datetime`** — legal effectivity is a calendar concept.
3. **Zero retrieval ⇒ `INSUFFICIENT_EVIDENCE`, not `is_compliant=True`** — the spec's behavior is
   a false-green correctness bug.
4. **No `StreamingResponse`** — 202 + poll; structured verdicts need the complete object.
5. **Sync engine → async** (`asyncpg`); the spec's `async def` over a sync engine blocks the event loop.
6. **`datetime.utcnow()` → server-side `now()`** — deprecated and clock-drifty.
7. **Verdict is tri-state** — a boolean cannot express "no governing law found".
8. **Multi-tenant vector partitioning** = global corpus + temporal/jurisdiction filtered ANN +
   RLS on the policy side — the honest interpretation of the spec's title.
