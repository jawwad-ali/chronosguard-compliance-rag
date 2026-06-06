The spec is read. I have everything I need to design the data architecture domain. Returning the design as raw markdown.

---

## Data Architecture & Temporal Model

This domain owns the entire PostgreSQL design: the physical schema, the temporal model, the vector strategy, Row-Level Security, and the Alembic/SQLModel toolchain. The spec's `SQLModel` sketch (sync engine, naive `datetime.utcnow`, no tenancy, no supersession, `is_active` bool as the temporal mechanism) is a starting point — I correct it below where it conflicts with the locked decisions (async, RLS, temporal correctness).

### 1. Keys, timestamps, soft-delete (foundational decisions)

**Primary keys: `BIGINT` identity for everything.** Decision: integer surrogate keys (`GENERATED ALWAYS AS IDENTITY`), not UUID. Rationale: in a single-Postgres shared-schema model the keys never leave the trust boundary, B-tree and HNSW locality is better with monotonic ints, and FKs are half the width. The classic UUID argument (clients mint IDs, multi-master merge) does not apply — we have one writer per row class. **Exception:** anything exposed in a URL or an API token gets a separate opaque `public_id` (`TEXT`, ULID or `secrets.token_urlsafe`) so we never leak row counts or enable enumeration. So: internal `id BIGINT`, external `public_id TEXT UNIQUE`.

**Timestamps: `TIMESTAMPTZ`, always, server-defaulted.** The spec's `datetime.utcnow()` (naive, app-side) is wrong for a temporal-correctness system — it loses tz and drifts from DB clock. Convention: `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()` maintained by a single trigger `set_updated_at()` applied to mutable tenant tables. App-layer `default_factory` is *not* trusted for these.

**Soft-delete stance: minimal.** Only `organizations` and `org_policies` carry `deleted_at TIMESTAMPTZ NULL` (tenant offboarding, policy retirement need an audit trail). Audit runs/findings are *append-only and never deleted* (they are the evidence record). Regulatory data is *never deleted* — it is temporally retired via dates/supersession (see §3). No global soft-delete framework; it pollutes every query with `WHERE deleted_at IS NULL` and fights RLS.

**Money/dates:** legal effectivity is **`DATE`, not timestamp.** A regulation comes into force "on 1 July 2026", not at a microsecond. Using `DATE` removes a whole class of tz-boundary bugs in temporal queries. The spec used `datetime` for `effective_date`; I override to `DATE`.

### 2. Table inventory

**Global (shared corpus, RLS-bypassed, ingestion-written):**
- `regulatory_documents` — parent gazette/SRO/circular metadata.
- `regulatory_chunks` — hierarchical chunks + vector + temporal/jurisdiction columns.
- `supersessions` — directed edges: chunk/document A is replaced/amended by B.
- `jurisdictions` — small reference table (`code`, `name`, `parent_code`) so `PK`, `PK-SINDH`, `EU` validate and nest.

**Tenant-scoped (RLS-enforced):**
- `organizations` — the tenant root. **`tenant_id` here is the org's own `id`.**
- `api_keys` — auth principals (MVP uses API keys, not user accounts — see §6).
- `org_policies` — logical policy document (current pointer).
- `org_policy_versions` — immutable versioned text (versioning lives here, not on the policy).
- `audit_runs` — one execution of `/compliance/audit`.
- `audit_findings` — individual violations produced by a run (the `PolicyViolation` rows).

### 3. The temporal model

**Decision: pragmatic uni-temporal valid-time, plus append-only system audit on the few tables that need it — NOT full bitemporal.** Full bitemporal (separate system-time and valid-time axes on every row, `_history` shadow tables) is enterprise cosplay for an MVP and quadruples query complexity. We model exactly one thing the domain actually requires: **valid time** — "what law was in force on date X". System-time auditing ("what did our DB *believe* the law was last Tuesday") is real but DEFERRED; we approximate it with immutable `ingested_at`/`created_at` and never-deleted rows, which is enough to reconstruct most disputes.

**Mechanism: half-open date interval `[effective_date, expiration_date)` + supersession graph.** Each `regulatory_chunk` carries:

- `effective_date DATE NOT NULL` — when this text came into force.
- `expiration_date DATE NULL` — when it ceased (NULL = still open-ended). Half-open: a row is in force on `d` iff `effective_date <= d AND (expiration_date IS NULL OR d < expiration_date)`.
- `is_active BOOLEAN` from the spec is **dropped as a stored authority** — it is a denormalized cache of "is in force *today*" that goes stale silently and is the #1 temporal-correctness bug. In-force is *always* derived from dates relative to the as-of date. (If a fast "current corpus" filter is wanted later, a `GENERATED` column or partial index can recompute it, not a hand-set bool.)

**"As-of date X" query** is a single deterministic predicate, ANDed before the vector ORDER BY:

```sql
WHERE c.jurisdiction = :jur
  AND c.effective_date <= :as_of
  AND (c.expiration_date IS NULL OR c.expiration_date > :as_of)
  AND NOT EXISTS (                       -- not superseded as of the date
    SELECT 1 FROM supersessions s
    WHERE s.superseded_chunk_id = c.id
      AND s.supersession_effective_date <= :as_of
  )
ORDER BY c.embedding <=> :qvec
```

**Supersession / retroactive amendment.** This is the subtle case the spec hand-waves. An amendment is itself a new document with its *own* effective date, and it does two things: (a) it inserts new chunks with their own `[effective_date, …)`, and (b) it *closes* the interval of the rules it replaces by setting their `expiration_date` and recording an edge in `supersessions`. We never mutate the old text content.

```sql
CREATE TABLE supersessions (
    id                          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    superseded_chunk_id         BIGINT NOT NULL REFERENCES regulatory_chunks(id),
    superseding_chunk_id        BIGINT     NULL REFERENCES regulatory_chunks(id), -- NULL = pure repeal
    superseded_document_id      BIGINT NOT NULL REFERENCES regulatory_documents(id),
    superseding_document_id     BIGINT     NULL REFERENCES regulatory_documents(id),
    relation                    TEXT   NOT NULL,  -- 'amends' | 'repeals' | 'replaces'
    supersession_effective_date DATE   NOT NULL,  -- the DATE the change takes legal force
    note                        TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT supersessions_relation_chk
        CHECK (relation IN ('amends','repeals','replaces'))
);
```

**Retroactive amendment** (a law passed in Sept 2026 that legally takes effect 1 Jan 2026) is represented honestly: the *superseding* chunk gets `effective_date = 2026-01-01` (its valid-time), while `created_at`/`ingested_at` records Sept (system-time). A query "as-of March 2026" run *today* therefore correctly returns the retroactive rule, because validity keys off `effective_date`, not ingestion. The old rule's interval is closed at `2026-01-01` and the `supersessions.supersession_effective_date = 2026-01-01`. This is exactly why we separate the two date concepts even without full bitemporality — it costs one extra column and buys retroactivity correctness. The honest limitation: an audit *re-run* today cannot reproduce what we would have answered in February (before the amendment was ingested). That bitemporal "as-known-of" replay is DEFERRED; we accept it for MVP because audit_runs snapshot their own results (§5).

**SQLModel sketch (global tables, corrected to async/typed):**

```python
import datetime as dt
from pgvector.sqlalchemy import Vector, HALFVEC  # see §4
from sqlalchemy import Column, Index, text
from sqlmodel import Field, SQLModel

class RegulatoryDocument(SQLModel, table=True):
    __tablename__ = "regulatory_documents"
    id: int | None = Field(default=None, primary_key=True)
    public_id: str = Field(index=True, unique=True)
    title: str = Field(index=True)
    issuing_body: str = Field(index=True)            # SECP, SBP
    document_type: str = Field(index=True)           # SRO, Circular, Gazette
    jurisdiction: str = Field(foreign_key="jurisdictions.code", index=True)
    source_url: str
    published_date: dt.date
    sha256: str = Field(unique=True)                 # ingestion idempotency
    ingested_at: dt.datetime = Field(
        sa_column_kwargs={"server_default": text("now()")})

class RegulatoryChunk(SQLModel, table=True):
    __tablename__ = "regulatory_chunks"
    id: int | None = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="regulatory_documents.id", index=True)
    chunk_index: int                                  # order within doc
    content: str
    legal_citation: str                               # "Section 12-B(4)(a)"
    heading_path: str                                 # "Part II > Ch 3 > S.12-B" (hierarchy)
    jurisdiction: str = Field(foreign_key="jurisdictions.code", index=True)
    effective_date: dt.date = Field(index=True)
    expiration_date: dt.date | None = Field(default=None, index=True)
    embedding: list[float] = Field(
        sa_column=Column(HALFVEC(1536)))              # halfvec, see §4
```

A composite/partial index supports the temporal+jurisdiction prefilter:
```sql
CREATE INDEX ix_chunks_jur_eff ON regulatory_chunks (jurisdiction, effective_date, expiration_date);
```

### 4. Vector strategy & "Multi-Tenant Vector Partitioning"

**The spec's "Multi-Tenant Vector Partitioning" is a misnomer and I'm naming it as such.** The regulatory corpus is *global* (shared across tenants) — there is nothing tenant-specific to partition by tenant. The real, valuable partitioning axis is **jurisdiction + temporal validity**, and the real goal is: *filtered* ANN search where the date/jurisdiction predicate doesn't wreck recall. So "multi-tenant vector partitioning" is implemented as **jurisdiction-keyed filtered HNSW with pgvector 0.8 iterative scans.** Tenant isolation of *queries* is irrelevant here because every tenant searches the same lawful corpus; isolation matters only for the *policy* side (no vectors there in MVP).

**Index decision: HNSW, not IVFFlat.** Rationale: the corpus is modest (thousands→low-tens-of-thousands of chunks for an MVP), churns incrementally (nightly ingest), and IVFFlat needs a representative dataset to train lists and degrades on incremental growth. HNSW has no training step, better recall at low latency, and tolerates incremental inserts — the right default for a small, growing, filtered corpus.

**Distance op: cosine (`vector_cosine_ops` / `halfvec_cosine_ops`)** to match OpenAI embeddings (the spec's `cosine_distance` / `<=>`).

**halfvec: yes.** Decision: store and index as `halfvec(1536)` (16-bit float). Rationale: text-embedding-3-small vectors tolerate fp16 with negligible recall loss, it halves storage and HNSW index size (relevant on Neon where storage and memory matter), and speeds index build. We keep the raw `vector` only if a later re-rank needs full precision — DEFERRED. Build:

```sql
CREATE INDEX ix_chunks_embedding_hnsw
ON regulatory_chunks
USING hnsw (embedding halfvec_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

`m=16, ef_construction=64` are the sane pgvector defaults for this scale; query-time `SET hnsw.ef_search = 40` (tune up for recall). **Filtered search uses pgvector 0.8 iterative scan** so the date/jurisdiction `WHERE` doesn't starve the result set:
```sql
SET hnsw.iterative_scan = strict_order;   -- session/txn-scoped, set per request
```
**Jurisdiction-keyed partial HNSW (the actual "partitioning"):** for the two or three hot jurisdictions (`PK` first) build *partial* indexes so the graph only contains in-scope vectors:
```sql
CREATE INDEX ix_chunks_emb_pk ON regulatory_chunks
USING hnsw (embedding halfvec_cosine_ops) WHERE jurisdiction = 'PK';
```
This keeps the PK graph small and fast and is trivially correct (the planner picks it when the predicate matches). Native Postgres table partitioning by jurisdiction is **DEFERRED** — not worth the DDL/FK complexity until the corpus is large and multi-jurisdiction is live.

**Neon build strategy:** HNSW build is memory-bound. Set `maintenance_work_mem` high for the build session, and for bulk seed/ingest, **load rows first, build the index after** (`CREATE INDEX` post-load is far faster than incremental insert into an existing HNSW). Use Neon DB branching to build/validate index changes on a branch before promoting.

### 5. Tenant-scoped tables (sketch)

```python
class Organization(SQLModel, table=True):
    __tablename__ = "organizations"
    id: int | None = Field(default=None, primary_key=True)   # == tenant_id
    public_id: str = Field(unique=True, index=True)
    name: str
    home_jurisdiction: str = Field(foreign_key="jurisdictions.code")
    created_at: dt.datetime = Field(sa_column_kwargs={"server_default": text("now()")})
    deleted_at: dt.datetime | None = None

class OrgPolicy(SQLModel, table=True):                       # logical doc
    __tablename__ = "org_policies"
    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="organizations.id", index=True)
    title: str
    current_version_id: int | None = Field(default=None, foreign_key="org_policy_versions.id")
    deleted_at: dt.datetime | None = None

class OrgPolicyVersion(SQLModel, table=True):                # immutable text
    __tablename__ = "org_policy_versions"
    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="organizations.id", index=True)
    policy_id: int = Field(foreign_key="org_policies.id", index=True)
    version_no: int
    body: str
    created_at: dt.datetime = Field(sa_column_kwargs={"server_default": text("now()")})

class AuditRun(SQLModel, table=True):
    __tablename__ = "audit_runs"
    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="organizations.id", index=True)
    policy_version_id: int | None = Field(foreign_key="org_policy_versions.id")
    jurisdiction: str
    as_of_date: dt.date                  # the temporal anchor of this audit (snapshotted!)
    is_compliant: bool | None = None     # NULL while running
    model: str                           # gpt model id used
    retrieved_chunk_ids: list[int] = Field(sa_column=Column(JSONB))  # provenance
    created_at: dt.datetime = Field(sa_column_kwargs={"server_default": text("now()")})

class AuditFinding(SQLModel, table=True):                    # == PolicyViolation
    __tablename__ = "audit_findings"
    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="organizations.id", index=True)
    run_id: int = Field(foreign_key="audit_runs.id", index=True)
    offending_policy_text: str
    legal_rule_text: str
    citation: str
    source_chunk_id: int | None = Field(foreign_key="regulatory_chunks.id")  # traceability
    source_url: str
    risk_level: str                      # CHECK in ('HIGH','MEDIUM','LOW')
    suggested_fix: str
```

`audit_runs.as_of_date` and `retrieved_chunk_ids` are the **system-time substitute**: every run snapshots exactly which corpus rows it reasoned over, so a finding remains explainable even after later supersessions mutate the live corpus. `tenant_id` is denormalized onto *every* tenant table (even children like `audit_findings`) so RLS is a flat per-row check with no joins.

### 6. RLS design (complete)

**Auth principal for MVP: `api_keys`, not user accounts.** Decision: machine-to-machine API key per org (hashed with SHA-256, lookup by prefix). User accounts/RBAC are DEFERRED — the MVP is backend-core and n8n/Next.js call it as services. The API key resolves to a `tenant_id` at the edge; FastAPI sets the tenant context per request; RLS enforces it.

**Role model — the app role is deliberately NOT the table owner.** RLS is bypassed by table owners and superusers and by anyone with `BYPASSRLS`. So:
- `cg_owner` — owns all tables, runs migrations/Alembic. Never used by the running API.
- `cg_app` — the API's role. `NOLOGIN`-parented login role, **no `BYPASSRLS`**, granted only `SELECT/INSERT/UPDATE` (no `DELETE` on append-only tables) on the tenant tables and `SELECT` on global tables. Because it is not the owner, RLS *always* applies to it. This is the crux: if the app connected as the owner, RLS would be silently inert.
- `cg_ingest` — ingestion CLI role with write access to global tables only. Global tables either have RLS disabled (they're shared) or a permissive read-all policy; ingestion writes via `cg_ingest`/`cg_owner`.

```sql
-- 1. Tenant context helper (no app GUC typo footguns)
CREATE FUNCTION app_current_tenant() RETURNS bigint
LANGUAGE sql STABLE AS $$
  SELECT NULLIF(current_setting('app.tenant_id', true), '')::bigint
$$;

-- 2. Enable + FORCE RLS on every tenant table (FORCE so even table owner is bound in tests)
ALTER TABLE org_policies        ENABLE ROW LEVEL SECURITY;
ALTER TABLE org_policies        FORCE  ROW LEVEL SECURITY;
-- ... repeat for org_policy_versions, audit_runs, audit_findings, api_keys, organizations

-- 3. One policy per tenant table (USING for read/update/delete, WITH CHECK for write)
CREATE POLICY tenant_isolation ON org_policies
  USING      (tenant_id = app_current_tenant())
  WITH CHECK (tenant_id = app_current_tenant());
-- organizations uses id instead of tenant_id:
CREATE POLICY tenant_isolation ON organizations
  USING (id = app_current_tenant()) WITH CHECK (id = app_current_tenant());

-- 4. Grants: app role is least-privilege, never owner
GRANT SELECT ON regulatory_documents, regulatory_chunks, supersessions, jurisdictions TO cg_app;
GRANT SELECT, INSERT, UPDATE ON org_policies, org_policy_versions TO cg_app;
GRANT SELECT, INSERT ON audit_runs, audit_findings TO cg_app;   -- append-only: no UPDATE/DELETE
```

**Global tables and the BYPASS pattern.** Global tables (`regulatory_*`, `jurisdictions`, `supersessions`) have **no RLS** — they're shared corpus, and `cg_app` has read-only grant. The "bypass" for admin/ingestion is *role-based*, not policy-based: ingestion connects as `cg_ingest`/`cg_owner`. There is no `tenant_id` to bypass on global data; keeping RLS off them avoids a needless permissive policy. The only nuance: `audit_findings.source_chunk_id` FKs into a global table — fine, since reading global rows is allowed for all.

**Setting context per request (FastAPI dependency, async):**
```python
async def tenant_session(api_key: str, engine) -> AsyncIterator[AsyncSession]:
    tenant_id = await resolve_api_key(api_key)         # -> org id, 401 if unknown
    async with AsyncSession(engine) as s:
        # set_config(_, _, is_local=true) => scoped to this transaction only
        await s.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        yield s
```
**Critical: `is_local = true` (transaction-scoped).** With a connection pool (asyncpg/pgbouncer), a session-scoped GUC would leak the previous request's tenant onto a reused connection — a cross-tenant data-leak bug. Transaction-local setting + "one transaction per request" eliminates it. If a NULL tenant ever reaches a policy, `tenant_id = NULL` is `UNKNOWN` → zero rows (fail-closed), which is the safe default.

### 7. Alembic + SQLModel integration

**Bootstrapping.** `env.py` imports the SQLModel metadata (`SQLModel.metadata`) as `target_metadata`, runs **async** (`connectable = create_async_engine(...)`, `run_sync(do_run_migrations)`). Migration `0001` does `CREATE EXTENSION IF NOT EXISTS vector` *before* any table that uses a vector column, and creates the roles/grants.

**Autogenerate gotchas (the real traps):**
1. **`pgvector` columns:** autogenerate emits `Vector`/`HALFVEC` types Alembic can't render without the import. Add `from pgvector.sqlalchemy import Vector, HALFVEC` to `script.py.mako`'s import block (or a `render_item` hook), or every generated migration breaks on import. Also configure `compare_type=False` for vector columns or autogen churns spurious type-change ops.
2. **HNSW indexes & RLS DDL are invisible to autogenerate.** Alembic only diffs the ORM metadata; it knows nothing about `CREATE INDEX … USING hnsw`, `CREATE POLICY`, `ENABLE RLS`, partial indexes, triggers, or `set_config`. **All of these go in hand-written `op.execute("""…""")`** blocks with matching `op.execute("DROP …")` in `downgrade()`. Treat them as first-class migration content, not afterthoughts.
3. **Naming convention** must be set on the metadata *before* first autogen, or constraint names are non-deterministic and downgrades break:
```python
SQLModel.metadata.naming_convention = {
  "ix": "ix_%(table_name)s_%(column_0_name)s",
  "uq": "uq_%(table_name)s_%(column_0_name)s",
  "ck": "ck_%(table_name)s_%(constraint_name)s",
  "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
  "pk": "pk_%(table_name)s",
}
```
4. **SQLModel duplicate-table:** importing models twice raises `Table already defined`; centralize model imports in one `models/__init__.py` that `env.py` imports once.
5. **`server_default`/`now()` & `GENERATED IDENTITY`:** set these via `sa_column_kwargs`/explicit DDL; autogen otherwise flip-flops between client and server defaults on every run — pin them.

### 8. Seed / sample data plan

A `typer` CLI command `cg seed` loads a small, realistic fixture (JSON in `seeds/`) via `cg_ingest`, covering the temporal edge cases the tests assert on:
- **SECP SRO "Funds Settlement"** v1: `effective 2024-01-01`, `PK`, chunk says "settle within 7 business days."
- **SECP SRO Amendment** v2: `effective 2026-06-01`, supersedes v1 (`relation='amends'`, `supersession_effective_date=2026-06-01`), chunk says "settle within 3 business days" — drives the spec's PocketPay example. v1's `expiration_date` set to `2026-06-01`.
- **SBP Banking Directive**: `PK`, open-ended, KYC retention rule — a second issuing body.
- **An expired circular**: `effective 2020-01-01`, `expiration_date 2022-01-01` — must *never* surface for `as_of >= 2022`.
- **A retroactive amendment**: ingested "now" (2026) but `effective_date 2026-01-01` — proves valid-time vs system-time separation.
- Two `organizations` ("PocketPay", "Acme") with one `org_policy` + version each and an `api_key` per org — to exercise RLS cross-tenant denial in tests.

Embeddings are generated at seed time via the real provider abstraction (or a deterministic fake-embedder in CI to avoid OpenAI calls/cost), then `CREATE INDEX` is run *after* load.

## Open risks in my domain
- **Filtered-HNSW recall under tight temporal predicates.** If a jurisdiction has many superseded chunks, the `WHERE` may filter out most HNSW candidates; iterative scan mitigates but needs `ef_search`/`iterative_scan` tuning and a recall test harness — unproven until real corpus volume exists.
- **No bitemporal replay.** We cannot reconstruct "what the audit would have said before amendment X was ingested." Mitigated by snapshotting `retrieved_chunk_ids` per run, but a true as-known-of query is impossible without the deferred system-time axis.
- **RLS correctness hinges on connection discipline.** Any code path that connects as `cg_owner`, forgets `is_local=true`, or runs multiple requests per transaction silently defeats isolation. Needs an explicit cross-tenant integration test as a CI gate.
- **Supersession data quality is human-entered.** A missed `expiration_date`/edge means a repealed rule keeps surfacing as in-force — a correctness (not availability) failure that's invisible without a temporal-consistency lint over the corpus.
- **halfvec recall assumption** for text-embedding-3-small is asserted, not measured; if fp16 quantization degrades retrieval on legal text, we revert the column to full `vector(1536)` (a migration + index rebuild, cheap at MVP scale but a known unknown).