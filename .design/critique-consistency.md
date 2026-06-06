I have the spec and all five domain designs. The findings below are based on careful cross-reading; no further file inspection is needed since this is a consistency review of the provided designs against each other and the spec.

# Cross-Domain Consistency & Integration Review — ChronosGuard

Findings are numbered, severity-tagged (BLOCKER = will break at integration / silent data bug; MAJOR = real contradiction needing a ruling; MINOR = naming/drift cleanup). For each I quote both sides, rule which wins, and why.

---

## BLOCKER findings

### 1. Primary-key type contradiction: `BIGINT` vs `UUID` for tenant entities — the schemas literally will not compile together

This is the single most pervasive contradiction. Domain 1 (data owner) is explicit:

> Domain 1: "**Primary keys: `BIGINT` identity for everything.** Decision: integer surrogate keys (`GENERATED ALWAYS AS IDENTITY`), not UUID… So: internal `id BIGINT`, external `public_id TEXT UNIQUE`."
> `Organization.id: int … # == tenant_id`; `AuditRun.id: int`; `AuditFinding.id: int`.

Domain 3 (API) builds its entire contract and RLS on UUID:

> Domain 3: `class Principal(BaseModel): tenant_id: UUID`; `class AuditRun(BaseModel): id: UUID`; `class AuditFinding(BaseModel): id: UUID`.
> RLS policy: `USING (tenant_id = current_setting('app.tenant_id', true)::uuid)`.
> `ApiKey: id(uuid) · tenant_id(fk)`.

Domain 4 also mints UUIDs (`ingestion_jobs.id uuid PRIMARY KEY DEFAULT gen_random_uuid()`), and Domain 1 says `regulatory_documents.id` is `BIGINT` while Domain 3's `AuditFinding` references `document_id: int; chunk_id: int` (consistent with Domain 1) but its own `AuditRun.id` is UUID.

**Which side wins: Domain 1 (BIGINT internal id + opaque `public_id TEXT` external).** Rationale: (a) it is the locked data-architecture owner's call and its reasoning (single writer, no client-minted IDs, HNSW/B-tree locality, narrow FKs) is correct for this topology; (b) Domain 3's own concern — not leaking row counts / enabling enumeration in URLs — is already solved by Domain 1's `public_id`. The fix is mechanical but mandatory: every Domain 3 API schema field typed `UUID` that maps to a row identity must become the opaque `public_id` string in the API surface, resolved to the internal `BIGINT` server-side. Critically, **the RLS policy cast `::uuid` must become `::bigint`** (see finding 2) and Domain 1's `app_current_tenant()` already returns `bigint` — so Domain 3's policy SQL is wrong as written and Domain 1's is right.

### 2. Two incompatible RLS context helpers ship in the same migration set — `::bigint` vs `::uuid`, and a function vs inline cast

Domain 1 defines a helper function and bigint cast:

> Domain 1: `CREATE FUNCTION app_current_tenant() RETURNS bigint … SELECT NULLIF(current_setting('app.tenant_id', true), '')::bigint`; `CREATE POLICY tenant_isolation ON org_policies USING (tenant_id = app_current_tenant())`.

Domain 3 inlines a different cast directly in the policy:

> Domain 3: `CREATE POLICY tenant_isolation ON org_policies USING (tenant_id = current_setting('app.tenant_id', true)::uuid) WITH CHECK (...)`.

These are mutually exclusive — only one `CREATE POLICY tenant_isolation ON org_policies` can exist. Beyond the uuid/bigint clash (resolved by finding 1 → bigint), there's a subtle correctness divergence: Domain 1 wraps the GUC in `NULLIF(..., '')` before casting, Domain 3 does not. **Domain 3's bare `current_setting(...)::uuid` throws `invalid input syntax` if the GUC is ever set to empty string `''` rather than unset** — a fail-*open*-to-500 path rather than fail-closed-to-zero-rows.

**Which side wins: Domain 1's `app_current_tenant()` function with `NULLIF(...,'')::bigint`.** Rationale: centralizing the cast in one STABLE function (a) gives one place to audit the security-critical predicate, (b) the `NULLIF` guard makes empty-string-vs-NULL both fail closed, matching the fail-closed invariant all three of Domain 1/3/5 claim. Domain 3 and Domain 5 must reference `app_current_tenant()`, not re-inline `current_setting`.

### 3. The audit execution path defeats RLS — background worker has no tenant context, writes tenant-scoped rows

Domain 3 moves audit execution off the request thread into a DB-drained background runner:

> Domain 3: "runner: claim queued row (`UPDATE ... SET status='running' ... WHERE status='queued' RETURNING ... with FOR UPDATE SKIP LOCKED`) → retrieval_service → provider.chat → **insert findings** → status='succeeded'".

But the runner does not authenticate via `X-API-Key`, so the `tenant_session` dependency (the only thing that runs `SELECT set_config('app.tenant_id', …, true)`) never fires. Domain 3's own risk bullet admits it:

> Domain 3 risk: "any future code that … uses `BackgroundTasks` touching tenant tables without re-setting context… will silently lose isolation (fails *closed* to empty results, but still a bug)."

It is worse than "fails closed": `audit_findings` and `audit_runs` are tenant-scoped with a `WITH CHECK` policy (Domain 1 §6). A worker INSERT of a finding with no `app.tenant_id` set evaluates `tenant_id = app_current_tenant()` where the function returns NULL → `WITH CHECK` is UNKNOWN → **the INSERT is rejected**. So the entire async audit pipeline (the core product loop) cannot write its results at all under RLS. Domain 5's leak test ("a test with *no* tenant context set must return zero tenant-scoped rows") will pass for SELECT but the worker's INSERT path is untested and broken.

**Which side wins: the worker must set tenant context from the claimed `audit_runs.tenant_id` before doing any tenant-scoped work.** Rationale: RLS is the locked, load-bearing control; the runner must read its tenant from the job row (which it owns — `audit_runs.tenant_id` per Domain 1) and call `set_config('app.tenant_id', str(run.tenant_id), true)` inside the same transaction, exactly like the request path. Concretely: claiming the queued row is itself a tenant-scoped read, so the *claim* query must run as a privileged step (either `cg_owner`/a maintenance role that reads the queue cross-tenant, or a dedicated nullable-RLS path), then re-enter tenant context per claimed run. This needs an explicit design decision none of the three relevant domains (1/3/5) actually pinned. **Mandatory addition to Domain 5's RLS test suite: a worker-path INSERT test, not just SELECT isolation.**

### 4. `is_active` is simultaneously "dropped as an authority", "kept and redefined", and "set on confirmation/supersession" — three domains disagree on whether the column even exists

Domain 1 removes it as stored state:

> Domain 1: "`is_active BOOLEAN` from the spec is **dropped as a stored authority**… In-force is *always* derived from dates… (If a fast 'current corpus' filter is wanted later, a `GENERATED` column or partial index can recompute it, not a hand-set bool.)"

Domain 2 keeps it but redefines it as derived, and introduces *new* columns instead of a supersession table:

> Domain 2: "`is_active` is kept but redefined as `expiration_date IS NULL AND superseded_at IS NULL` — derived". And requires columns `superseded_at timestamptz`, `superseded_by_chunk_id int`, `content_hash text` on `regulatory_chunks`.

Domain 4 treats `is_active` as a hand-set stored boolean it writes during confirmation and supersession:

> Domain 4: "`is_active` on its chunks is only set `true` on confirmation"; "sets the **old** doc's chunks `is_active=false` and `expiration_date = new_doc.effective_date`".

Domain 3 filters on it as a stored column:

> Domain 3: "applying the same temporal filter as audit (effective ≤ as_of < expiration, `is_active`)."

This is a four-way contradiction on a correctness-critical column. Worse, Domain 1 and Domain 2 model **supersession in fundamentally different ways**: Domain 1 uses a separate `supersessions` edge table with `supersession_effective_date` and derives "not superseded as of date" via `NOT EXISTS`; Domain 2 uses a denormalized `superseded_at timestamptz` column directly on the chunk. Domain 2's `as_of_predicate` references `RC.superseded_at` and `RC.expiration_date` as columns — **this SQLAlchemy filter will not compile against Domain 1's schema, which has neither `superseded_at` nor a stored `is_active` on the chunk.**

**Which side wins: a blend, with Domain 1's date-derived authority as the spine.**
- **In-force authority = dates + supersession, never a stored `is_active`** (Domain 1 wins on the principle; the stale-boolean bug is real).
- **Supersession mechanism = Domain 1's `supersessions` edge table** (wins over Domain 2's `superseded_at` column), because (a) it cleanly models pure repeal (NULL superseding chunk), partial amendment, and the retroactive case Domain 1 details, and (b) Domain 4's supersession workflow ("X supersedes Y", operator-confirmed) maps naturally to inserting an edge row.
- **Therefore Domain 2's `as_of_predicate` must be rewritten** to the `NOT EXISTS (supersessions …)` form (which Domain 1 already wrote) instead of `RC.superseded_at`. Domain 2's instinct (don't trust `is_active` for point-in-time) is correct and reinforces Domain 1; only its column mechanism loses.
- **Domain 4 must stop setting `is_active=false`** and instead (on supersession confirm) insert a `supersessions` row + set the superseded chunks' `expiration_date`. This is exactly Domain 1's "close the interval + record the edge" pattern.
- If a fast "today" flag is genuinely wanted, it is a `GENERATED`/partial-index per Domain 1, owned by Domain 1 — not a hand-set boolean three domains write.

### 5. `effective_date`/`expiration_date` column type: `DATE` (Domain 1) vs `timestamptz` (Domains 2, 3, 4) — temporal comparisons will be inconsistent

Domain 1 overrides the spec deliberately:

> Domain 1: "legal effectivity is **`DATE`, not timestamp.**… The spec used `datetime` for `effective_date`; I override to `DATE`." Schema: `effective_date: dt.date`, `expiration_date: dt.date | None`.

Every consumer assumes timestamp:

> Domain 2: `as_of_predicate(jurisdiction: str, as_of: datetime)`, comparing `RC.effective_date <= as_of`; "`as_of = request.target_date or now() # tz-aware UTC; reject naive datetimes`".
> Domain 3: `as_of_date: date | None` on `AuditCreate` (date — consistent with Domain 1!) but `AuditFinding.effective_date: date` (consistent) — Domain 3 is actually mostly fine here.
> Domain 4: `ALTER TABLE … ADD COLUMN expiration_date timestamptz` and `effective_date` evidence handling treats it as date.

So the real clash is **Domain 2 (compares against a tz-aware `datetime` `as_of`)** and **Domain 4 (declares `expiration_date timestamptz` in its DDL)** versus Domain 1's `DATE`. Comparing a `DATE` column to a `timestamptz` parameter forces an implicit cast and reintroduces exactly the tz-boundary bugs Domain 1 eliminated (e.g., `effective_date <= as_of` where `as_of` is `2026-06-06T23:00:00+05:00` behaves differently than a pure date compare around midnight UTC).

**Which side wins: Domain 1's `DATE`.** Rationale: "what law was in force on date X" is a calendar-date question; legal commencement is a date, not an instant. The fix: **Domain 2's `as_of` must be a `datetime.date`, not `datetime`**, and its "reject naive datetimes at the API boundary" rule is replaced by "resolve to a `date` in the jurisdiction's civil calendar." Domain 4's `expiration_date timestamptz` DDL is wrong and must be `DATE`. Note Domain 1 and Domain 4 also disagree on whether the table is altered (`ALTER TABLE regulatory_documents ADD COLUMN expiration_date`) vs defined once — these two must be reconciled into a single migration authored by Domain 1 (see finding 12).

### 6. Embedding column nullability and dimension/type conflict: `halfvec(1536) NOT NULL` (Domain 1) vs `vector(1536)` nullable (Domains 2, 4)

Domain 1 makes two pinned choices:

> Domain 1: "store and index as `halfvec(1536)` (16-bit float)"; index `USING hnsw (embedding halfvec_cosine_ops)`; SQLModel `embedding: list[float] = Field(sa_column=Column(HALFVEC(1536)))` (NOT NULL).

Domain 4 needs nullable for resumable embedding and assumes full `vector`:

> Domain 4: "embedding made NULLABLE so chunks persist before embeddings land. `ALTER TABLE regulatory_chunks ALTER COLUMN embedding DROP NOT NULL`"; index implied as `vector_cosine_ops`.

Domain 2 assumes full-precision `vector`:

> Domain 2: "Index: `CREATE INDEX ... USING hnsw (embedding vector_cosine_ops)`."

Two independent conflicts: (a) **halfvec vs vector** drives the index operator class (`halfvec_cosine_ops` vs `vector_cosine_ops`) — they are not interchangeable, and Domain 2/4 writing `vector_cosine_ops` against a `halfvec` column fails. (b) **NOT NULL vs nullable** — Domain 4's resumable-ingest design (persist chunk rows, embed later, `WHERE embedded_at IS NULL`) structurally requires the embedding column to be nullable, directly contradicting Domain 1's NOT NULL.

**Which side wins:** On (a), **Domain 1's `halfvec`** — it owns the vector strategy and the storage/recall trade-off reasoning is sound for Neon; Domains 2 and 4 must use `halfvec_cosine_ops` everywhere they name an index/op. On (b), **Domain 4's nullable embedding wins over Domain 1's NOT NULL**, because resumable per-batch embedding is a concrete operational requirement and the alternative (embed-before-insert) defeats Domain 4's crash-recovery design. Domain 1 should relax the column to nullable and instead enforce "embedded before retrievable" via the `extraction_status='confirmed'` gate + a partial HNSW index `WHERE embedding IS NOT NULL`. This also composes with Domain 4's review-gating (finding 9).

### 7. Retrieval filter omits the `extraction_status='confirmed'` gate — unconfirmed/low-confidence law can surface in audits

Domain 4 makes the review gate a core correctness promise:

> Domain 4: "the document is written with `extraction_status='review'` and **excluded from retrieval** until an operator confirms"; "This guarantees **no low-confidence regulatory text silently affects an audit** — the core correctness promise."

But neither Domain 1's canonical as-of query nor Domain 2's `as_of_predicate` filters on `extraction_status`:

> Domain 1 query: `WHERE c.jurisdiction = :jur AND c.effective_date <= :as_of AND (...) AND NOT EXISTS (supersessions …)` — no status filter.
> Domain 2 `as_of_predicate`: jurisdiction + effective + expiration + superseded — no status filter.

So a document sitting in `review` (or `pending`) with embeddings already generated (Domain 4 embeds before confirmation in its state machine: `chunking → embedding → review`) **is fully retrievable**, breaking Domain 4's stated guarantee.

**Which side wins: Domain 4's gate must be added to the canonical predicate.** Rationale: it is a correctness promise, and the predicate lives in "one reusable SQLAlchemy filter helper" (Domain 2 §2) — so the fix is one clause: `AND d.extraction_status = 'confirmed'` (joining `regulatory_documents`) in `as_of_predicate`. This is load-bearing and must be in the shared helper, the `POST /regulatory/search` path (Domain 3), and the eval harness, or the three diverge again.

---

## MAJOR findings

### 8. Two `ingestion_jobs`/`audit_runs` background-worker patterns that don't compose — `locked_at` lease (Domain 4) vs `FOR UPDATE SKIP LOCKED` status flip (Domain 3)

Domain 3's audit runner and Domain 4's ingestion worker are described as "the same pattern" by each, but they are two *different* patterns:

> Domain 3 (audit): "claim queued row (`UPDATE ... SET status='running' ... FOR UPDATE SKIP LOCKED`)"; reaper "resets stale `running` rows (claimed > N min ago) back to `queued`" — but `audit_runs` (Domain 1) has **no `locked_at`/`locked_by` column**, so "claimed > N min ago" has nothing to measure.
> Domain 4 (ingestion): explicit lease columns `locked_at timestamptz, locked_by text`; "jobs `locked_at` older than 15 min … are reclaimed."

So Domain 4's `ingestion_jobs` has a real lease; Domain 3's `audit_runs` lease is referenced in the risk section but the column doesn't exist in Domain 1's `AuditRun` model. The reaper Domain 3 wants cannot be built against the schema as designed.

**Which side wins: Domain 4's explicit-lease pattern, applied to both tables.** Rationale: a `status` flip alone can't detect a worker that crashed *after* claiming (the row is stuck in `running` forever); Domain 4 already solved this with `locked_at`. Domain 1 must add `locked_at TIMESTAMPTZ NULL, locked_by TEXT NULL` to `audit_runs` (it owns the table), and Domain 3's reaper keys off `locked_at`. Both workers should share one claim/lease helper.

### 9. Ingestion writes `regulatory_chunks` but the locked role model may forbid it — `cg_ingest` grants are unspecified for the new ingestion tables

Domain 1 defines the role model precisely for the tables it knew about:

> Domain 1: "`cg_ingest` — ingestion CLI role with write access to global tables only." Grants shown: `GRANT SELECT … TO cg_app` on `regulatory_*`; ingestion "writes via `cg_ingest`/`cg_owner`."

Domain 4 introduces a *new* global table and writes to it from both a CLI and an **API webhook endpoint**:

> Domain 4: new `ingestion_jobs` table; `POST /api/v1/ingest/webhook` (n8n) "inserts jobs"; worker writes `regulatory_documents`, `regulatory_chunks`.

The integration seam: the **API process runs as `cg_app` (no write on global tables)**, but Domain 4's webhook + worker, if hosted in the same FastAPI app/process (Domain 3 places `routers/admin.py` and `workers/audit_runner.py` in-process), would need to INSERT into `ingestion_jobs`, `regulatory_documents`, and `regulatory_chunks` — which `cg_app` cannot do. Domain 1 never granted `cg_app` any write on global tables (correctly, for the audit path), and never mentioned `ingestion_jobs` at all.

**Which side wins: ingestion must run under `cg_ingest`, even when triggered via the API.** Rationale: keeping `cg_app` read-only on the global corpus is a deliberate, correct least-privilege boundary (Domain 1). Therefore the n8n webhook handler and the worker must acquire a **separate `cg_ingest` connection/engine**, not reuse the request's `cg_app` session. This is an un-pinned architectural decision: the API needs *two* DB roles (request path = `cg_app`, ingestion path = `cg_ingest`). Domain 1 must add `ingestion_jobs` to its table inventory and grant `cg_ingest` write on it; Domain 3 must provision a second engine for the ingestion router/worker. Also: `ingestion_jobs.triggered_by` and the `cg_ingest` path are global/un-tenant-scoped, which is consistent (ingestion is tenant-agnostic per all domains) — good.

### 10. Endpoint inventory mismatch: ingestion webhook path, auth scheme, and job-status endpoint disagree between Domain 3 and Domain 4

Domain 3 (API owner) and Domain 4 (ingestion owner) both specify the ingestion trigger surface, differently:

> Domain 3: `POST /api/v1/admin/ingest` (scope `admin`, `X-API-Key`); `GET /api/v1/admin/ingest/{job_id}`. Request body `IngestRequest{ source_url, issuing_body, document_type, jurisdiction, published_date, effective_date, expiration_date, supersedes_document_id }`.
> Domain 4: `POST /api/v1/ingest/webhook` (auth = static shared secret header `X-Ingest-Token`, **not** API key); status "polled via `chronos status` / a future `/api/v1/ingest/jobs/{id}` endpoint." Request body `{ source_url, issuing_body, jurisdiction, document_type, discovered_at, source_etag }`.

Three concrete divergences: (a) **path** (`/admin/ingest` vs `/ingest/webhook`); (b) **auth** (org-scoped `admin` API key vs a global static `X-Ingest-Token`); (c) **request body** (Domain 3 makes the *caller* supply `effective_date`/`expiration_date`/`supersedes_document_id`; Domain 4 *derives* those via LLM extraction and forbids the caller from setting legal dates).

**Which side wins: mostly Domain 4 on body, Domain 3 on auth+path.**
- **Body: Domain 4 wins.** Having n8n (or any caller) hand-supply `effective_date` defeats Domain 4's entire LLM-metadata-extraction + review-gate design and would let a trigger inject legal dates with no verification. The caller supplies *hints* (`issuing_body`, `jurisdiction`, `document_type`, `source_url`, `source_etag`); the backend derives the legal temporal fields. Domain 3's `IngestRequest` with `effective_date`/`supersedes_document_id` should be dropped.
- **Auth + path: Domain 3 wins.** A single static `X-Ingest-Token` is a weaker, separate auth scheme that bypasses the unified API-key model and per-key revocation/observability (Domains 3 & 5 bind `tenant_id`/`api_key_id` into every log line — a static token breaks that). Use `POST /api/v1/admin/ingest` with `admin`-scoped API key. n8n holds an `admin` key; no second credential type.
- **Status endpoint: build it.** Domain 4 calls `/api/v1/ingest/jobs/{id}` "a future endpoint"; Domain 3 specs `GET /admin/ingest/{job_id}`. Pick Domain 3's path and ship it in MVP (n8n needs a poll target — Domain 4's n8n contract is "POST to enqueue, GET to confirm").

### 11. Provider abstraction is defined three times with three different `Protocol` shapes and import locations

Three domains each declare the embedding/chat provider abstraction with incompatible signatures and module paths:

> Domain 2: `app/providers/embeddings.py` — `class EmbeddingProvider(Protocol): async def embed(self, texts: list[str]) -> list[list[float]]`; plus `app/providers/llm.py` `ChatProvider`.
> Domain 3: `services/provider/base.py` — `EmbeddingProvider, ChatProvider Protocols`; `services/provider/openai.py`.
> Domain 4: `app/providers/embeddings.py` — `class EmbeddingProvider(Protocol): model: str; dims: int; async def embed(self, texts: list[str]) -> list[list[float]]`.

Domain 4's protocol adds `model: str` and `dims: int` attributes that Domain 2's lacks; the module path is `app/providers/` (Domains 2, 4) vs `src/chronosguard/services/provider/` (Domain 3) vs `apps/api/src/chronosguard/providers/` (Domain 5's tree). They cannot all be right.

**Which side wins: one provider package, Domain 4's richer Protocol, Domain 3/5's package location.** Rationale: (a) there must be exactly one `EmbeddingProvider`/`ChatProvider` consumed by both retrieval (Domain 2) and ingestion (Domain 4) — the embedding model **must** be identical on both sides for cosine validity (Domain 2 says so explicitly), so a shared abstraction is mandatory, not optional. (b) Domain 4's `model`/`dims` attributes are useful (ingestion stamps `embedding_model` on chunks; retrieval can assert dimension) — adopt the superset. (c) Location: under the package root (`src/chronosguard/providers/`), not nested in `services/` — retrieval, audit, and ingestion all import it, so it's not a service-private. The `src/chronosguard/` layout (Domain 3/5) wins over Domain 2/4's bare `app/` (see finding 14).

### 12. `regulatory_*` schema is authored by two domains via incompatible mechanisms — `CREATE TABLE` (Domain 1) vs `ALTER TABLE … ADD COLUMN` (Domain 4)

> Domain 1: full `CREATE TABLE`/SQLModel definitions for `regulatory_documents`, `regulatory_chunks` including `heading_path`, `legal_citation`, `chunk_index`, `sha256`.
> Domain 4: "`ALTER TABLE regulatory_documents ADD COLUMN content_hash …, version …, supersedes_doc_id …, extraction_status …, raw_markdown …`" and "`ALTER TABLE regulatory_chunks ADD COLUMN chunk_index …, heading_path …, token_count …, embedding_model …, embedded_at …`".

These overlap and conflict on the *same columns*: both define `chunk_index` and `heading_path` on `regulatory_chunks` (Domain 4 re-adds what Domain 1 already has → migration error), Domain 1 has `sha256` on the document while Domain 4 adds `content_hash` (two columns for the same concept — see finding 13), and Domain 4 adds `supersedes_doc_id` to the document while Domain 1 models supersession only via the `supersessions` edge table (finding 4).

**Which side wins: Domain 1 owns the canonical `CREATE TABLE`; Domain 4's needed columns are merged into it, not bolted on via ALTER.** Rationale: Domain 1 is the data-architecture owner and the schema must be defined once. Domain 4's genuinely-new columns (`token_count`, `embedding_model`, `embedded_at`, `raw_markdown`, `source_etag`, `version`, `extraction_status`) are legitimate and should be folded into Domain 1's model definitions. The duplicated columns (`chunk_index`, `heading_path`) collapse to one. `supersedes_doc_id` is dropped in favor of the `supersessions` edge (finding 4). Net: one migration `0001`/`0002` set, authored by Domain 1, incorporating Domain 4's ingestion columns.

### 13. Idempotency hash named/typed two ways and keyed two ways — `sha256 TEXT UNIQUE` on content (Domain 1) vs `content_hash char(64)` + `uq(source_url, content_hash)` (Domain 4); API idempotency keyed on `source_url` (Domain 3)

> Domain 1: `RegulatoryDocument.sha256: str = Field(unique=True) # ingestion idempotency`.
> Domain 4: `content_hash char(64) NOT NULL`; `CREATE UNIQUE INDEX uq_doc_url_hash ON regulatory_documents(source_url, content_hash)`.
> Domain 3: "`Idempotency-Key` keyed on `source_url`" for `/admin/ingest`.

Three idempotency concepts collide: Domain 1 makes the **content hash globally unique** (same content can never be ingested twice even from two URLs); Domain 4 makes **(url, hash) unique** (same content at two URLs is allowed — correct for re-published gazettes and cross-referenced docs); Domain 3 dedupes at the **API layer on `source_url` alone**, which Domain 3's own risk bullet flags as wrong ("if regulators re-publish a corrected PDF at the same URL, the dedupe will suppress a legitimate re-ingest").

**Which side wins: Domain 4's `(source_url, content_hash)` composite, single column named `content_hash`.** Rationale: Domain 1's globally-unique `sha256` is too strict — it would reject legitimately identical text published under two SROs. Domain 4's reasoning about re-published/versioned gazettes is the more careful treatment of the actual legal-document domain. Therefore: rename Domain 1's `sha256` → `content_hash`, drop its global UNIQUE, adopt Domain 4's composite unique index. **Domain 3's API-level `Idempotency-Key` on `source_url` must change to `(source_url, source_etag)` or be downgraded to a fast-path hint only** — the authoritative dedup is the DB composite, exactly as Domain 4 designed (ETag fast-path → content-hash check).

---

## MINOR findings

### 14. Directory layout / package root contradiction: `app/` vs `src/chronosguard/`, and `apps/api/...` monorepo nesting

> Domains 2 & 4: top-level `app/` package (`app/retrieval/`, `app/ingestion/`, `app/providers/`).
> Domain 3: `src/chronosguard/` (src-layout), with `src/chronosguard/services/`, `routers/`, `models/`.
> Domain 5: `apps/api/src/chronosguard/` (monorepo), and notably places retrieval/audit/ingestion **flat under `chronosguard/`** (`chronosguard/retrieval/`, `chronosguard/audit/`, `chronosguard/ingestion/`), not under a `services/` subpackage as Domain 3 does.

**Which side wins: Domain 5's `apps/api/src/chronosguard/` monorepo + src-layout** (Domain 5 owns repo shape). But Domain 3's `services/`/`repositories/`/`routers/` internal structure is the more disciplined layering and should be adopted *inside* `chronosguard/`. The clash to resolve: Domain 5 puts `retrieval/`, `audit/`, `ingestion/` as top-level subpackages; Domain 3 puts logic under `services/`. Recommendation: keep domain subpackages top-level (`chronosguard/retrieval/`, `chronosguard/audit/`, `chronosguard/ingestion/` — matches Domains 2/4/5) and reserve `services/` for thin orchestration glue only. Either way, **`app/` (Domains 2, 4) must be renamed to the `chronosguard/` package** so imports resolve.

### 15. Python version pinned three ways: 3.12 (locked stack & Domains 1/5) vs spec's 3.11+

> Locked stack + Domain 5 `requires-python = ">=3.12"`, `target-version = "py312"`.
> Spec §1.2: "FastAPI (Python 3.11+)".

**Which side wins: 3.12** (the locked decision and Domain 5's `pyproject.toml` are authoritative; the spec's "3.11+" is a floor that 3.12 satisfies). No real conflict — just confirm no domain accidentally targets 3.11 features-only. Non-issue, flagged for completeness.

### 16. Streaming: spec mandates `StreamingResponse`; all backend domains correctly reject it — but verify the UI contract is told

> Spec §1.2: "asynchronous execution threads for non-blocking stream handling (`StreamingResponse`)."
> Domain 2: "**MVP returns complete JSON. No SSE.**" Domain 3: "SSE and websockets are rejected for MVP."

**Which side wins: Domains 2 & 3 (no streaming; 202 + poll).** This correctly overrides the spec's `StreamingResponse` aspiration, with sound reasoning (structured-output validation + quote-grounding need the complete object). Consistent across backend domains — good. The only action: the **Next.js contract (deferred) must be documented as poll-based**, which Domain 2 and Domain 3 both note. No contradiction between domains; flagging only because it overrides the spec and the UI team must not build against `StreamingResponse`.

### 17. `AuditRun.is_compliant` semantics: spec/Domain 1 boolean vs Domain 2's first-class `INSUFFICIENT_EVIDENCE`

> Spec & Domain 1: `is_compliant: bool | None`. Domain 3: `is_compliant: bool | None # null until succeeded`.
> Domain 2: "Zero candidates… is **not** 'compliant'… We return a first-class `INSUFFICIENT_EVIDENCE` verdict at the run level (`status="no_corpus"`)" and a 3-value `Verdict` enum.

A boolean `is_compliant` cannot represent the three-state outcome (compliant / violation / insufficient-evidence) that Domain 2 correctly insists on. Domain 3's `AuditRun.status` enum is `queued/running/succeeded/failed` — it has no slot for "succeeded-but-no-corpus".

**Which side wins: Domain 2's three-state verdict.** Rationale: a false "compliant" on empty retrieval is the worst failure mode in a compliance tool (Domain 2's argument is correct and the spec's `return AuditResponse(is_compliant=True, …)` is a genuine bug). Domain 1's `audit_runs.is_compliant bool|NULL` should become an enum/verdict column (`COMPLIANT|VIOLATION|INSUFFICIENT_EVIDENCE`), and Domain 3's `AuditRun.is_compliant: bool|None` API field becomes that verdict. Keep `status` for job lifecycle only.

---

## Verification of the four locked decisions

- **RLS tenancy:** Honored in principle by Domains 1/3/5, but with the BIGINT/UUID cast clash (findings 1–2) and a broken worker write-path (finding 3) and missing ingestion role separation (finding 9). Honored only after those are fixed. Domain 4 correctly treats regulatory data as global/un-tenant-scoped.
- **All-OpenAI:** Honored everywhere (text-embedding-3-small + Structured Outputs in Domains 2/4; thin provider abstraction in all). The triplicated abstraction (finding 11) is a consolidation issue, not a violation. No non-OpenAI provider appears.
- **Backend-first:** Honored — Next.js and n8n are contract-only in every domain (Domains 3/4/5 explicitly defer them). Good.
- **Managed PaaS (Neon + Render/Railway/Fly, no K8s):** Honored. Domain 5 picks Render; Domain 3 designs around Neon direct-vs-pooled endpoints; Domain 1 uses Neon branching. No Kubernetes anywhere. Consistent. One latent seam: Domain 3 wants the API on Neon's **direct** endpoint while Domain 4's n8n/burst tooling uses the **pooled** endpoint — compatible, but the two DB roles (finding 9) plus two endpoints must be wired in one `config.py`.

## Highest-priority resolutions (build-order)
1. **Finding 1+2 (PK type + RLS cast):** ratify BIGINT internal + `public_id`; one `app_current_tenant()::bigint`. Unblocks the entire schema/API/RLS triangle.
2. **Finding 4+5+6 (temporal authority, date type, vector type/nullability):** ratify dates-derived in-force + `supersessions` edge + `DATE` + `halfvec` nullable. Unblocks retrieval SQL compiling against the schema.
3. **Finding 3+9 (worker RLS context + `cg_ingest` second engine):** unblocks the async audit and ingestion write paths actually persisting under RLS.
4. **Finding 7 (`extraction_status='confirmed'` in the canonical predicate):** one clause, but it's a stated correctness promise — must land in the shared helper.
5. **Finding 10+12+13 (ingestion endpoint/body/auth + single schema author + idempotency key):** unblocks the n8n contract and prevents duplicate/colliding migrations.