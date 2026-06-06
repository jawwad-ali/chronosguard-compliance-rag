# Overengineering & MVP-Fit Critique — ChronosGuard

Reviewed against the spec (a deliberately thin, partly buzzword-laden blueprint) and the right-sizing directive: 1–3 people, weeks to ship, backend core. Findings numbered, severity-tagged. Over-builds first, then justified-corners-cut (the opposite failure), then a few that are correctly sized and should NOT be touched.

---

## A. OVERENGINEERING — cut or defer these now

### 1. [HIGH] `halfvec` quantization on a few-thousand-row corpus (Domain 1)
**Quoted:** *"halfvec: yes. Decision: store and index as `halfvec(1536)` … halves storage and HNSW index size (relevant on Neon where storage and memory matter)."*
At MVP scale the entire corpus is, by Domain 5's own cost model, ~50k chunks. 50k × 1536 × 4 bytes ≈ 300 MB raw, far less indexed — trivial on any Neon paid tier. You are trading **measurable, unproven recall risk on legal text** (Domain 1 lists this as an open risk) for storage savings you do not need. This is premature optimization that simultaneously *adds* a correctness risk.
**MVP-right:** plain `vector(1536)`, `vector_cosine_ops`. One data type, no fp16 recall question, no "revert migration" contingency.
**Trigger for halfvec later:** corpus crosses ~1M chunks OR Neon memory pressure shows in index-build/query metrics. Then measure recall delta on a golden set before flipping.

### 2. [HIGH] Jurisdiction-keyed *partial* HNSW indexes, hand-built per hot jurisdiction (Domain 1)
**Quoted:** *"for the two or three hot jurisdictions (`PK` first) build *partial* indexes so the graph only contains in-scope vectors … `CREATE INDEX ix_chunks_emb_pk … WHERE jurisdiction = 'PK'`."*
This is the "Multi-Tenant Vector Partitioning" buzzword from the spec being honored with real DDL it doesn't deserve yet. With one live jurisdiction (PK) at MVP, a partial index `WHERE jurisdiction='PK'` is functionally identical to a single full index — pure ceremony — but it commits you to per-jurisdiction migration DDL, planner-dependent index selection, and N indexes to rebuild on every schema change.
**MVP-right:** one HNSW index over the whole `embedding` column; let the `WHERE jurisdiction = :jur` predicate + iterative scan do the filtering. Domain 1 already specs iterative scan; that alone suffices at this scale.
**Trigger:** a single jurisdiction's in-force chunk count is large enough that filtered recall measurably degrades AND you have ≥3 active jurisdictions competing in one graph.

### 3. [MEDIUM] pgvector 0.8 `iterative_scan = strict_order` specified pre-measurement (Domains 1 & 2)
**Quoted:** *"Filtered search uses pgvector 0.8 iterative scan … `SET hnsw.iterative_scan = strict_order;`"*
Iterative scan is the *fix for a problem you have not yet observed* (HNSW returning too few rows after a restrictive filter). At thousands-to-50k chunks the post-filter result set is rarely starved. Specifying `strict_order` (the slower, stricter mode) by default is paying latency insurance against an unmeasured failure.
**MVP-right:** ship plain HNSW + the temporal/jurisdiction `WHERE`. Add iterative scan (and prefer `relaxed_order` first) only when the recall eval harness shows under-retrieval. Keep it as a one-line session GUC you can flip — which it is — so this is genuinely free to defer.
**Trigger:** recall@k eval drops below threshold specifically due to candidates filtered out post-ANN.

### 4. [MEDIUM] Three-role DB separation (`cg_owner` / `cg_app` / `cg_ingest`) (Domain 1)
**Quoted:** *"`cg_owner` … `cg_app` … `cg_ingest` — ingestion CLI role with write access to global tables only."*
`cg_owner` (migrations, non-RLS) and `cg_app` (non-owner, RLS-bound, no BYPASSRLS) are **load-bearing and justified** — that two-role split is the only thing making RLS actually enforce (keep it; see §13). But the *third* role, `cg_ingest`, earns nothing: ingestion writes only to global tables that have no RLS, and the CLI is operator-run, not internet-exposed. It adds a third credential to provision on Neon, rotate, and document.
**MVP-right:** two roles. Ingestion CLI connects as `cg_owner` (it already runs migrations/seeds and is operator-only). Revisit if ingestion ever becomes a network-reachable service with its own attack surface.
**Trigger:** ingestion runs as an automated, externally-triggered service (not operator CLI) and you want to cap its blast radius.

### 5. [MEDIUM] Two parallel job-execution designs that contradict each other (Domains 3 & 4)
**Quoted (D3):** *"in-process background runner using FastAPI `BackgroundTasks`/an `asyncio.TaskGroup` … draining a DB-backed queue (`audit_runs.status='queued'`) … `FOR UPDATE SKIP LOCKED`."*
**Quoted (D4):** *"`chronos worker run-once` … PaaS cron invokes `run-once` every minute."*
Two domains independently invented a Postgres-as-queue worker — one in-process for audits, one cron-polled for ingestion — with separate state machines, lease columns, and reaper logic (`audit_runs.status` vs `ingestion_jobs.status`/`locked_at`/`locked_by`/`attempts`/`max_attempts`). That's two queue implementations to build, test, and reap for a weeks-long MVP. The ingestion `ingestion_jobs` table in particular (full state enum `queued|fetching|parsing|chunking|embedding|review|done|failed|dead`, lease reclaim, dead-letter, retry CLI) is a mini-Celery.
**MVP-right:** pick **one** durable-job mechanism (a single `jobs` table with `kind ∈ {audit, ingest}`, `status`, `attempts`, `locked_at`) drained by one `chronos worker run-once` cron target. Audits don't need a different mechanism than ingestion. Collapse the two state machines into `queued → running → succeeded|failed` (+ `review` only for ingestion). The granular per-phase status enum (`fetching/parsing/chunking/embedding`) is observability theater — log the phase, don't persist it as job state.
**Trigger:** sub-second pickup latency or concurrent-worker scaling forces a real broker (arq+Redis) — at which point one abstraction swaps, not two.

### 6. [MEDIUM] Sync escape-hatch `POST /audits?wait=true` (Domain 3)
**Quoted:** *"`POST /audits?wait=true` … awaits the result inline up to a 25s budget, else falls back to 202 semantics."*
This is a second code path through the audit pipeline (inline await + timeout-fallback-to-async) built for a dashboard "quick check" that doesn't exist yet (UI is deferred). Two execution modes = two sets of edge cases (what happens to the row if the 25s budget trips mid-LLM? double-execution?).
**MVP-right:** one path — always 202 + poll. The poll loop is trivial for both n8n and the future UI.
**Trigger:** real UX feedback that polling latency hurts the dashboard's primary flow.

### 7. [MEDIUM] Keyset/cursor pagination everywhere from day one (Domain 3)
**Quoted:** *"Pagination — keyset/cursor (decided) … opaque base64 of (sort_value, id) … query does `WHERE (col, id) < (:c, :id)`."*
Keyset is the *correct* end state, but opaque-cursor encode/decode on every list endpoint (audits, findings, policies, documents, chunks) is real surface for a corpus measured in tens of thousands and a single tenant's handful of policies/audits. The justification — "grows under concurrent ingestion, offset rots" — is true at scale, not at MVP volume where a tenant has maybe dozens of audit runs.
**MVP-right:** simple `limit`/`offset` with a sane cap for tenant-scoped lists (policies, audits, findings — small N per tenant). Reserve keyset for the one genuinely large, concurrently-mutated list: `regulatory_chunks` browse. One pagination style for the big global table, plain offset for the small tenant tables.
**Trigger:** any tenant-scoped list realistically exceeds a few thousand rows, or pagination-during-ingestion skips become observable.

### 8. [LOW] RFC 9457 `application/problem+json` with URN error types (Domain 3)
**Quoted:** *"Errors → RFC 9457 `application/problem+json` … `type_: str = "urn:chronosguard:error:not-found"`."*
The full RFC 9457 envelope plus stable URN type slugs is a spec-compliance flourish. The *single consistent error shape* is justified (the UI/n8n need one shape — keep that). The `urn:chronosguard:error:*` registry of type URIs is the cosplay — nobody dereferences them, and you'll maintain a slug catalog for no consumer.
**MVP-right:** keep the one `ProblemDetail` Pydantic model and global handlers (genuinely good), but let `type` default to `"about:blank"` and drop the URN namespace scheme. Add typed URIs if/when a client actually switches on them.
**Trigger:** an API consumer programmatically branches on error `type` URIs.

### 9. [LOW] Idempotency-Key machinery on audit + ingest creation (Domain 3)
**Quoted:** *"client sends `Idempotency-Key` header … store `(tenant_id, idempotency_key) → audit_run_id` unique … Same key + different body → `409 Conflict`."*
Full idempotency-key storage with body-mismatch conflict detection is Stripe-grade. For ingestion you *already* have natural idempotency: `content_hash` + `source_url` unique index (Domain 4). For audits, at-least-once retry creating a duplicate audit run is cheap and harmless (it's an append-only evidence record; dedup later if anyone cares).
**MVP-right:** rely on the existing `(source_url, content_hash)` unique constraint for ingest dedup (Domain 4 already built it — Domain 3's separate idempotency layer is redundant for ingest). Skip idempotency keys on audits entirely for MVP.
**Trigger:** n8n's retry behavior is observed creating costly duplicate audits, or a billing model makes duplicate audits expensive.

### 10. [LOW] `just` task runner as a new required binary on Windows (Domain 5)
**Quoted:** *"Task runner — DECISION: `just` (justfile). … installs cleanly on Windows via `winget`/`scoop`."*
Adding `just` is a non-Python binary every contributor must install, on a stack where `uv` already runs everything. The recipes are all `uv run …` wrappers. The `set shell := ["pwsh", ...]` with "CI overrides to bash" is exactly the cross-platform drift the choice was meant to avoid.
**MVP-right:** `uv run` plus a handful of scripts under `[tool.uv]`/a `tasks.py` (Typer — already a dependency for the CLI). Zero new binaries, no shell-dialect split.
**Trigger:** the polyglot repo grows non-Python tasks (Next.js build, etc.) that genuinely need a language-agnostic runner — i.e., when `web/` stops being a placeholder.

### 11. [LOW] `public_id` / ULID opaque external IDs alongside BIGINT internal keys (Domain 1)
**Quoted:** *"anything exposed in a URL or an API token gets a separate opaque `public_id` (`TEXT`, ULID …) so we never leak row counts or enable enumeration."*
Dual-key (internal BIGINT + external ULID) on every exposed entity is defense against enumeration/count-leakage that matters for public multi-tenant SaaS, not a backend consumed by n8n + one org dashboard behind API keys. Note the internal inconsistency: Domain 3's schemas expose raw `document_id: int` / `chunk_id: int` in `AuditFinding` and deep-links anyway — so the corpus side leaks integer IDs regardless, making the policy half-applied.
**MVP-right:** BIGINT everywhere, exposed directly. Tenant scoping is enforced by RLS, not ID opacity. Global corpus IDs are non-secret by definition.
**Trigger:** the API becomes publicly reachable to untrusted clients where row-count inference is a real threat.

### 12. [LOW] Live (paid, real-OpenAI) eval tier + offline recorded-response tier from day one (Domains 2 & 5)
**Quoted (D2):** *"Two tiers … Offline tier … recorded LLM responses … Live tier (nightly …) asserts `recall@8 ≥ 0.9` and `verdict_accuracy ≥ 0.85`."*
The eval *harness* and golden set are justified and high-value (keep). The two-tier CI machinery — cached `.npy` embeddings, recorded-response fixtures, pytest markers `eval_offline`/`eval_live`, nightly scheduled workflow with PR-comment reporter, `continue-on-error` semantics — is a lot of CI plumbing before there's a measured baseline to regress against.
**MVP-right:** build the golden set and a single `pytest -m eval` you run manually/locally against real OpenAI (cheap — Domain 5 estimates <$0.03/audit). Defer the nightly workflow, the reporter bot, and the recorded-response fixture system until the eval set is large enough that running it costs real money or time.
**Trigger:** eval suite runtime/cost makes per-PR or frequent runs painful, or the team grows enough that a nightly regression signal needs an owner.

---

## B. UNDER-BUILT — corners cut that will be expensive to retrofit (NOT overengineering; fix now)

### 13. [CRITICAL — keep, do not cut] The non-owner `cg_app` role + `FORCE RLS` + transaction-local `SET LOCAL`
**Quoted (D1):** *"if the app connected as the owner, RLS would be silently inert."* **(D3):** *"`is_local = true` (transaction-scoped) … a session-scoped GUC would leak the previous request's tenant onto a reused connection."*
This trio is correctly sized and is the security spine. If a reviewer is tempted to "simplify" by running the app as the Neon owner role or using session GUCs, that is a silent cross-tenant data leak. Retrofitting RLS after launch (re-permissioning, re-testing every query path) is brutal. **This is justified complexity — protect it with the mandatory cross-tenant leak test (D3/D5) as a blocking CI gate.**

### 14. [HIGH] Schema-additions contract drift between domains — pin it before any migration
Domain 1 models supersession as a **`supersessions` edge table** + closing `expiration_date`. Domain 2 requires **`superseded_at TIMESTAMPTZ` + `superseded_by_chunk_id`** columns on the chunk and writes its temporal predicate against `superseded_at`. Domain 4 sets **`is_active=false` + `expiration_date`** on supersession and keeps `is_active` as authority. **Three domains, three incompatible supersession mechanisms and three different opinions on whether `is_active` is authoritative or dropped.** This is not overengineering — it's an unreconciled contract that will produce a wrong temporal query (the product's entire differentiator). Cutting the reconciliation is the expensive corner.
**Fix now:** one decision, written once. Recommend Domain 1's: dates are authority (`effective_date`/`expiration_date` + `supersessions` table), `is_active` is dropped or a derived/generated convenience only. Domain 2's `as_of_predicate` must read the `supersessions` table (or the closed `expiration_date`), not a `superseded_at` column that Domain 1 doesn't create. Reconcile before writing migration 0001.

### 15. [MEDIUM] `effective_date` type conflict (DATE vs TIMESTAMPTZ) is unreconciled
Domain 1 deliberately makes legal effectivity **`DATE`** ("removes a whole class of tz-boundary bugs"). Domain 4's `ALTER TABLE` adds `expiration_date timestamptz` and the original spec uses `datetime`. Domain 2's predicate compares `effective_date <= as_of` where `as_of` is a tz-aware `datetime`. Mixed DATE/TIMESTAMPTZ comparisons are a silent correctness footgun in a temporal-correctness product.
**Fix now:** adopt Domain 1's `DATE` for all legal-effectivity columns uniformly; resolve `as_of` to a `DATE` at the API boundary. Cheap now, a data migration later.

### 16. [MEDIUM] Zero-candidate = `INSUFFICIENT_EVIDENCE`, not `is_compliant=True`
**Quoted (D2):** *"The spec's `return AuditResponse(is_compliant=True, …)` is a correctness bug I am overriding."*
This is the single most important correctness fix in the whole review and it is correctly identified. A compliance tool returning a false green check on "no law retrieved" is a liability event. **Keep it; make sure it survives into the actual `AuditResponse` contract** (Domain 3's `AuditRun.is_compliant: bool | None` supports it via null/status — verify the public schema carries a tri-state, not a bool).

### 17. [MEDIUM] Stale-`running` job reaper is named as a risk but not designed (Domains 3 & 4)
Both domains flag orphaned `running` jobs on dyno crash as an open risk, and both punt the reaper. For a money-spending, multi-minute pipeline on a PaaS that redeploys, a crashed-worker job stuck `running` forever is a near-certainty, not an edge case. This is a cheap thing to build now (a `WHERE status='running' AND locked_at < now() - interval '15 min'` reset on worker startup) and annoying to discover in prod.
**Fix now:** include lease-reclaim in the single unified worker (ties to finding #5). It's ~10 lines and removes a whole class of stuck-job incidents.

---

## C. CORRECTLY SIZED — explicitly do NOT touch

- **HNSW over IVFFlat** (D1/D2): right call for a small, incrementally-growing corpus; no training step. Leave it.
- **API keys over user auth** (D3): smallest credible scheme for machine consumers. Deferring user accounts/RBAC is correct.
- **testcontainers `pgvector/pgvector:pg16` for both local and CI** (D5): one mechanism, hermetic, no Neon secrets in CI. Deferring Neon-branch-per-PR is the right deferral. Keep.
- **mypy `strict` from day one** (D5): genuinely cheap on greenfield, brutal to retrofit. Justified.
- **No OCR / reject-and-flag scanned PDFs** (D4): correct scope cut for digital-native gazettes.
- **n8n as trigger-only, backend owns parsing** (D4): correct division; resist any pull to put parsing logic in n8n.
- **Reject streaming / SSE for MVP** (D2/D3): structured-output verdicts aren't usefully streamable; 202+poll is right.

---

## Top-line verdict
The five designs are, on balance, **well right-sized** — the architects mostly resisted enterprise cosplay and tagged deferrals honestly. The real risk here is not any single over-build; it's **finding #14**: three domains independently designed *three different supersession/temporal mechanisms*, and that contract must be reconciled to one before migration 0001 or the product's differentiator ships subtly wrong. The clearest pure over-builds to cut today are **#1 (halfvec)**, **#2 (partial per-jurisdiction HNSW)**, and **#5 (two parallel job-queue implementations)** — collapsing those three removes the most unearned complexity for an MVP. Everything in Section B should be treated as a pre-launch checklist, not a backlog.