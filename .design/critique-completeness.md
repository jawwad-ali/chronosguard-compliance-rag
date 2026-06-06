The spec is read. I have the original requirements and all five domain designs. Returning my completeness and risk critique as raw markdown.

---

# Completeness & Risk Review — ChronosGuard Compliance

The five domains are strong and internally coherent. The temporal model, RLS discipline, and grounding defenses are genuinely production-grade. My job is to find what is **missing** across the *combined* design versus the spec and versus production reality. Findings are numbered, ordered roughly by severity. Each has: why it matters, smallest MVP-credible mitigation (or explicit "accept the risk"). I flag cross-domain contradictions explicitly because those are where integration bugs hide.

---

### 1. CROSS-DOMAIN CONTRADICTION: primary key type is unresolved (BIGINT vs UUID). This breaks the API and RLS contracts as written.

**Why it matters.** Domain 1 (Data) explicitly decides **`BIGINT` identity** for all PKs with a separate opaque `public_id TEXT`. Domain 3 (API) writes RLS policies casting `current_setting('app.tenant_id', true)::uuid` and types every schema field as `id: UUID`, `tenant_id: UUID`. Domain 2 references `tenant_id` as bigint via `set_config(..., str(tenant_id))`. These cannot both be true. If the tenant PK is BIGINT but the RLS policy casts to `::uuid`, **every tenant-scoped query throws a cast error or silently returns zero rows** — and "silently zero rows" is exactly the fail-closed path that an integration test on a single tenant will *pass*, masking the bug until a second tenant exists. Domain 3's `AuditFinding` also exposes raw `document_id: int` and `chunk_id: int` to the client, directly contradicting Domain 1's "never leak row counts / enable enumeration" rule (and the spec's own `source_url`-based citation tracing).

**Mitigation.** Pin one identity strategy in a shared `models/base.py` before any migration is written: internal `BIGINT` + external `public_id` (Domain 1's call is correct for this single-writer system). Then (a) RLS policies cast `::bigint`, not `::uuid`; (b) every API response uses `public_id`, never the bigint; (c) `AuditFinding` exposes a `chunk_public_id` + `source_url`, not `chunk_id: int`. This is a one-paragraph ADR that prevents a multi-day integration stall.

---

### 2. CROSS-DOMAIN CONTRADICTION: the supersession model is specified three incompatible ways. Temporal correctness — the entire product — rides on resolving this.

**Why it matters.** Three domains model "rule X is replaced by rule Y" differently:
- **Domain 1**: a separate `supersessions` edge table, queried with `NOT EXISTS (... supersession_effective_date <= :as_of)`. `is_active` is *dropped entirely*.
- **Domain 2**: a `superseded_at TIMESTAMPTZ` + `superseded_by_chunk_id` column **on the chunk**, queried with `or_(RC.superseded_at.is_(None), RC.superseded_at > as_of)`. `is_active` *redefined as derived*.
- **Domain 4**: sets `is_active=false` and `expiration_date = new.effective_date` on superseded chunks at confirmation time. `is_active` is *authoritative and hand-set*.

These produce **different retrieval results for the same as-of query**. Domain 1's edge table is the only one that cleanly supports an amendment whose effective date differs from ingestion, but Domain 2's retrieval helper doesn't query that table at all, and Domain 4 writes the `is_active` flag that Domain 1 explicitly deleted. Worse, Domain 1 closes the old interval via `expiration_date` *and* records an edge — so the `NOT EXISTS` subquery is redundant with the `expiration_date` filter unless they can disagree, and if they *can* disagree, which wins? This is the load-bearing correctness mechanism and it is currently three mechanisms.

**Mitigation.** One owner (Data) writes the single canonical as-of predicate as a SQLAlchemy helper that *every* consumer imports — there must be exactly one `as_of_predicate()` in the codebase, and Domain 2's copy must be deleted, not reconciled. Decide: is supersession expressed by **closing `expiration_date`** (simple, one column, sufficient for full repeals) **or** by the **edge table** (needed for partial amendments and "what replaced this")? For MVP I'd pick: `expiration_date` is the authority for *retrieval filtering* (one predicate, fast, indexed), and the `supersessions` edge table exists *only for the diff-UI lineage* ("this rule was amended by that one"), never in the hot query path. Drop `superseded_at` and hand-set `is_active` as retrieval authorities. Make this a CI temporal-consistency test: assert no chunk is returned by the as-of predicate that also has `expiration_date <= as_of`.

---

### 3. Retroactive amendment corrupts already-completed audits, and nothing detects it. Audit reproducibility is asserted but not actually deliverable.

**Why it matters.** Domain 1 explicitly accepts that a retroactive amendment (passed Sept, effective-dated Jan) means "an audit re-run today cannot reproduce what we would have answered in February." But the combined design goes further and breaks something subtler: an audit **already run and stored** in February against the old rule is now *wrong* — its findings cite a rule that, as of the audit's own `as_of_date`, no longer reflects the law. Domain 1 snapshots `retrieved_chunk_ids`, which preserves *what we retrieved*, but the stored `is_compliant=true` verdict is now a **false compliance record** that a customer may have relied on. In a compliance tool this is the single most dangerous failure: a green checkmark that later silent-flipped to red with no notification. The spec's whole value proposition is "regulatory drift detection," and a retroactive amendment is drift that invalidates prior audits — yet no domain detects or flags it.

**Mitigation (cheap).** When ingestion closes a rule's interval with an `effective_date` **earlier than `now()`** (i.e., a retroactive/backdated amendment), run a query: `SELECT DISTINCT run_id FROM audit_runs WHERE jurisdiction = ? AND as_of_date >= new.effective_date AND <retrieved a now-superseded chunk>`. Mark those runs `stale=true` (one boolean column on `audit_runs`) and surface them in the API as "this audit may be affected by a later retroactive amendment — re-run recommended." This is one column + one query at ingestion confirmation time. Do **not** auto-rerun (cost/surprise); just flag. Accept that perfect bitemporal replay is deferred, but do *not* accept silent staleness.

---

### 4. Date-less and ambiguous-effective-date documents have no defined home in the data model or retrieval.

**Why it matters.** Domain 4 names the problem ("with immediate effect," "w.e.f.," phased commencement, retrospective effect) as an open risk and routes low-confidence extractions to a `review` queue. But Domain 1's schema declares `effective_date DATE NOT NULL` — so a document the LLM *cannot* date has **nowhere to be stored** without a fabricated date, and Domain 2's as-of predicate (`effective_date <= :as_of`) silently *excludes* any chunk whose date was guessed wrong on the early side or included one guessed wrong on the late side. "With immediate effect" is genuinely ambiguous: effective on the *publication* date or the *gazette notification* date? These can differ by weeks in Pakistani practice. A NOT NULL column forces a decision the system can't honestly make, and the review gate keeps the doc *out of retrieval entirely* until a human picks a date — meaning a just-published, in-force regulation is **invisible to audits** during the review backlog.

**Mitigation.** (a) Allow `effective_date` to default to `published_date` with an explicit `effective_date_source` enum (`extracted` | `defaulted_to_published` | `operator_confirmed`) so the provenance is honest and queryable. (b) Decide the "immediate effect" convention once and document it (recommend: publication date, the conservative choice for catching violations early). (c) Surface `effective_date_source != operator_confirmed` as a `needs_review` flag *on audit findings that depend on that chunk*, rather than hiding the chunk — better a flagged finding than a missed rule.

---

### 5. Urdu / bilingual gazette reality is completely absent — a correctness gap specific to the Pakistan focus the spec mandates.

**Why it matters.** SECP and especially SBP gazette content is frequently **bilingual (English + Urdu)** or Urdu-primary, and the official *legally authoritative* text is sometimes the Urdu version. No domain mentions language at all: there is no `language` column, `pymupdf4llm` extraction will interleave Urdu (RTL) and English into garbled reading order, `text-embedding-3-small` handles Urdu far worse than English (degrading retrieval recall on exactly the authoritative text), and the heading-detection regexes (Domain 4) are English-only (`PART`, `CHAPTER`, `SECTION`) and will fall straight through to token-splitting on any Urdu-structured doc. The product is pitched as "Pakistan fintech focus" — this is not an edge case, it's the home market.

**Mitigation.** For MVP, make the limitation *explicit and safe* rather than silently wrong: (a) add a `language` column to `regulatory_documents`; (b) at ingestion, detect script (cheap: Unicode range heuristic for Arabic/Urdu block) and **route non-English-primary docs to the `review` queue with `reason='non_english_unsupported'`** instead of producing garbage chunks; (c) document "MVP supports English-language gazettes; Urdu/bilingual is DEFERRED" as a scoping decision, not an accident. Accept the risk of not *handling* Urdu, but do not accept *silently mis-ingesting* it.

---

### 6. OpenAI outage / degradation has no audit-side degradation path; the audit endpoint hard-fails with no partial-result or cached-embedding fallback.

**Why it matters.** Domain 2 and 4 both have tenacity retries (good), and Domain 3 maps OpenAI failure to `ProviderError` 502 (good). But the *audit* path has two independent OpenAI dependencies — query embedding **and** the GPT verdict — and if either is down, the entire audit fails. There is no decision for: (a) a multi-clause audit where 38 of 40 clauses succeed and 2 hit exhausted retries — Domain 2 marks them `status="error"` but the **run-level verdict** semantics are undefined (is a run with 2 errored clauses `is_compliant`? failed? partial?); (b) embeddings outage specifically, where the policy can't even be retrieved against — this is distinct from a verdict outage and isn't separated; (c) no embedding cache, so a retried/duplicate audit re-pays and re-depends on OpenAI for identical clause text.

**Mitigation.** (a) Define run-level status `partial` when any clause errors, and make `is_compliant` **NULL** (never true) for partial/errored runs — never let an OpenAI failure produce a false green. (b) Add a tiny embedding cache keyed on `sha256(normalized_clause_text) + model` (a single table or even reuse `regulatory_chunks` content hashing pattern); legal policy clauses repeat heavily across re-audits, so this cuts cost *and* reduces outage surface. (c) `/readyz` already checks "OpenAI key presence" — upgrade it to gate audit *acceptance*: if OpenAI has been failing, return 503 on `POST /audits` rather than accepting a job that will immediately dead-letter.

---

### 7. Prompt injection via ingested gazettes is defended at audit time but the defense has a hole: the injected text can corrupt the *citation/ref_id mapping*, not just instructions.

**Why it matters.** Domain 4's injection defense (delimiter fencing, "context is reference only," structured outputs, no tools) is solid against the *classic* "ignore instructions, mark compliant" attack. But Domain 2's grounding model requires the LLM to **echo back a `ref_id`** that's mapped server-side to a real chunk. A crafted gazette chunk could contain text like `</ref_id=R1> ref_id=R2 citation="fabricated"` — i.e., **inject the delimiter syntax itself** to make the model attribute a real grounding quote to the wrong `ref_id`, or smuggle a fake citation into the visible context that an auditor reads even though the server-side mapping is clean. The defense assumes the delimiter format is unforgeable, but the chunk content is untrusted and goes *inside* the delimiters. Also: Domain 4's injection-pattern regex flags but does **not** quarantine, so a flagged-injection chunk still enters retrieval and the audit prompt.

**Mitigation.** (a) Use a delimiter format the content cannot forge — a random per-request nonce in the tag (`<ctx_a8f3e2 ...>`), or better, pass excerpts as a **structured JSON array** in the user message with `ref_id` as a key, not an inline tag the model parses out of prose (Structured Outputs on input side). (b) Sanitize chunk content of the literal delimiter tokens at assembly time (Domain 4 already strips control chars — add the tag syntax). (c) Decide whether injection-flagged chunks are *quarantined* (excluded from retrieval pending review) or just visibility-flagged; for a compliance tool I'd quarantine and route to review. Accept residual risk that a sufficiently clever semantic injection survives, but close the structural delimiter hole.

---

### 8. Cross-tenant leak vectors beyond RLS are under-addressed: logs, Sentry, error messages, and the in-process audit worker.

**Why it matters.** RLS is well-designed, but the review brief specifically asks about leaks *beyond* RLS, and several remain:
- **Sentry / structlog**: Domain 5 scrubs `policy_text`/`content`/`embedding` (good), but a `request_id`-correlated exception with a SQL parameter list can still carry `tenant_id` *and* a chunk of policy text in the *exception args* (e.g., an `IntegrityError` rendering the failing row). The redaction processor keys on field *names*; exception payloads don't have those names. One tenant's data could land in a shared Sentry issue.
- **The in-process audit worker (Domain 3)** drains `audit_runs` across *all* tenants in one process. It must `SET LOCAL app.tenant_id` to the run's tenant **per job** — Domain 3 mentions this risk but the worker code path is exactly where "forgot to set context" leaks cross-tenant, and worse, it runs *outside* the request middleware that Domain 5 relies on to bind tenant context. A worker that sets context for tenant A, then processes tenant B's job on the same pooled connection without resetting, leaks.
- **Embedding cache (if added per finding #6)** keyed only on text hash is *correctly* tenant-agnostic for regulatory chunks but would cross-tenant-share *policy* clause embeddings — acceptable (embeddings aren't reversible to a useful degree) but should be a conscious decision, not accidental.

**Mitigation.** (a) Sentry `before_send` should additionally truncate/scrub `extra`, `exception values`, and SQL params, not just named fields — strip anything over N chars. (b) The audit worker must wrap each job in its own transaction with `SET LOCAL app.tenant_id = <job.tenant_id>` and an assertion that context is set before any tenant query; add this specific worker path to the mandatory RLS test suite (Domain 5's tests cover the request path, not the worker path). (c) Document the embedding-cache tenant-sharing decision explicitly.

---

### 9. Migration rollback story is shallow: the drift gate and `downgrade -1` test do not cover the irreversible operations the design actually uses.

**Why it matters.** Domain 5 tests `alembic downgrade -1 && upgrade head` on the latest revision and runs `alembic check` for drift. But the design is full of operations Alembic autogenerate *cannot* see and that are *not* trivially reversible: HNSW index creation (Domain 1 — minutes to rebuild on a real corpus, so a downgrade that drops it is not "free"), RLS policies, the `pgvector` extension, partial indexes, `halfvec` column type (Domain 1 keeps open the option to revert `halfvec`→`vector`, which is a full table rewrite + index rebuild, not a `downgrade -1`). Domain 5 itself notes the drift gate "cannot catch a destructive migration." On Neon, a forward-only expand/contract discipline is correct, but the *first* migration creates roles (`cg_owner`/`cg_app`/`cg_ingest`) and a downgrade that drops roles while connections are using them will fail. The rollback story is "we test `downgrade -1`" but the real-world rollback is "restore the Neon branch," and those two aren't reconciled.

**Mitigation.** Make the rollback policy explicit: **forward-only in prod; rollback = Neon PITR/branch restore, not `alembic downgrade`.** Keep `downgrade` functions for *local dev* only and stop pretending they're a prod safety net. The CI `downgrade -1` test is fine as a hygiene check but should be labeled as such. Add a one-line runbook: "to roll back a bad deploy, restore the Neon branch to the pre-deploy timestamp and redeploy the prior image" — Domain 5 mentions PITR but never connects it to *migration* rollback specifically.

---

### 10. Zero-result and low-confidence paths are well-designed in Domain 2 but the run-level and API contract don't propagate them honestly.

**Why it matters.** Domain 2 correctly makes `INSUFFICIENT_EVIDENCE` a first-class clause verdict and overrides the spec's dangerous `is_compliant=True` on zero results. But this is a *clause-level* decision, and the **document/run-level rollup is underspecified**: Domain 1's `AuditRun.is_compliant: bool | None` and Domain 3's `is_compliant: bool | None` + `finding_count` have no field for "N clauses returned INSUFFICIENT_EVIDENCE" or "the whole corpus was empty for this jurisdiction." A run where *every* clause hit `no_corpus` should be loudly distinct from a run that's genuinely compliant — but the API `AuditRun` schema can't express the difference (both are `is_compliant`-ish). The Next.js diff UI (spec §2.3) cannot render "we have no law for PK as of this date" versus "you're compliant" — the worst possible ambiguity for a compliance product.

**Mitigation.** Add a run-level `coverage` summary to the `AuditRun` response: counts of `{violation, compliant, insufficient_evidence, error}` clauses, and an explicit run `status` value `no_applicable_law` when the corpus filter returned zero for the whole jurisdiction/date. Make `is_compliant` strictly tri-state-aware: `true` only if ≥1 clause was actually evaluated against real retrieved law AND no violations; `null` otherwise. This is a schema addition the UI owner needs *now* (it's a contract), not later.

---

### 11. Neon cold-start and connection-limit interaction with the audit worker is unaddressed.

**Why it matters.** Domain 3 handles cold-start for the *API* (`pool_pre_ping`, `pool_recycle`, direct endpoint). But two compounding issues remain: (a) Neon's free/launch tiers have **low connection ceilings** (often ~100, fewer effective with the direct endpoint), and the design now has *three* connection consumers — the API pool (5+5 overflow), the in-process audit worker, **and** the PaaS-cron ingestion worker (Domain 4, every minute) — none of which coordinate pool sizing. (b) Neon scale-to-zero means the *first* audit after idle eats a multi-second cold start *inside* the 25s sync-audit budget (Domain 3's `?wait=true`) and *inside* the OpenAI-call timeout window, compounding latency. (c) The ingestion cron worker connecting every 60s **keeps Neon warm**, which is good for latency but **defeats scale-to-zero cost savings** that the cost model (Domain 5, ~$19-25 Neon) implicitly assumes.

**Mitigation.** (a) Document a connection budget: API `pool_size` + worker + cron ≤ Neon tier limit, and put it in `config.py` as asserted-on-startup. (b) Either accept Neon stays warm (cron every 60s ⇒ no scale-to-zero ⇒ revise cost expectation upward) or move ingestion cron to every 5-15 min to allow idle windows — a conscious cost/latency tradeoff currently made by accident. (c) Add a connect-retry wrapper for the first-query-after-cold-start case (Domain 3 flags this as an open risk but ships nothing).

---

### 12. `is_active` survives in three domains as a query authority despite Domain 1 deleting it — a latent correctness bug that an index decision depends on.

**Why it matters.** This is the concrete fallout of finding #2, called out separately because it has a *physical* consequence. Domain 1's seed plan, Domain 4's supersession confirmation, and Domain 2's partial-index proposal all reference `is_active`. Domain 1 says it's dropped as authority but "a `GENERATED` column or partial index can recompute it." Domain 2 proposes partial HNSW indexes `WHERE jurisdiction = 'PK'`. Domain 1 proposes partial HNSW `WHERE is_active` implicitly via "current corpus filter." If `is_active` is a hand-set bool (Domain 4) and *also* a partial-index predicate, then a stale `is_active` doesn't just return a wrong row — it **silently excludes a valid row from the index**, an invisible recall failure that no temporal test catches because the row is simply absent from the ANN graph.

**Mitigation.** If `is_active` survives at all, it **must** be a `GENERATED ALWAYS` column derived from `expiration_date IS NULL` (never hand-set), so it cannot drift. Partial indexes should key on `jurisdiction` (stable) not `is_active` (mutable) to avoid index-membership churn on every supersession. Forbid hand-writing `is_active` anywhere in code review.

---

### 13. Ingestion idempotency keyed on `source_url` will suppress legitimate corrected-gazette re-ingests (acknowledged by two domains, never resolved).

**Why it matters.** Domain 3 flags this as an open risk ("regulators re-publish a corrected PDF at the same URL"), and Domain 4 *partially* solves it (`uq_doc_url_hash` on URL+content_hash, new version row on content change). But the two are inconsistent: Domain 3's `/admin/ingest` idempotency key is **`source_url` alone**, which would 200-dedupe a corrected re-publish *before* Domain 4's content-hash logic ever runs. The n8n contract (Domain 4) sends `source_etag` for skip-if-unchanged — but a corrected PDF at the same URL with the same ETag (regulators do reuse ETags carelessly) would be skipped entirely. A *corrected* regulation that's silently not re-ingested is a correctness failure: audits keep citing the uncorrected text.

**Mitigation.** Make the API idempotency key for ingestion **`source_url + content_hash`**, consistent with Domain 4 — which means the API must let the *fetch+hash* happen before dedup, i.e., dedup is a property of the ingestion job, not the HTTP request. The `Idempotency-Key` header should dedupe *duplicate webhook deliveries* (n8n at-least-once), keyed on the n8n-supplied delivery ID, **not** on `source_url`. Don't trust ETags for correctness — treat them as a *latency* optimization only, and always re-hash on a `force=true` path for operator-triggered re-ingest of suspected corrections.

---

### 14. No PII/data-residency or deletion (tenant-offboarding / GDPR-style) story for tenant policy text, which is confidential customer data.

**Why it matters.** Org policy text is the customer's confidential internal data, persisted in `org_policy_versions` (immutable) and snapshotted into `audit_runs` (Domain 2 recommends storing the clause array as JSONB for replay). Domain 1 gives `organizations` a `deleted_at` for offboarding — but soft-delete + RLS means the data **physically remains**, and `audit_runs` are explicitly "append-only and never deleted." A tenant requesting deletion (contractual or regulatory) cannot be honored: their policy text lives forever in immutable audit snapshots. For a compliance product sold to regulated fintechs, "we cannot delete your data on request" is itself a compliance problem and likely a sales blocker.

**Mitigation (MVP-credible).** Decide and document the hard-delete path for offboarding: a `cg_admin` operation that hard-deletes a tenant's `org_policies`, `org_policy_versions`, `audit_runs`, `audit_findings` by `tenant_id` (RLS-bypassing admin role, in one transaction). Audit *evidence* immutability and *customer deletion rights* genuinely conflict; resolve it explicitly — recommend: hard-delete on offboarding is allowed and overrides append-only, with a tombstone row recording the deletion event. Accept that this weakens the evidentiary guarantee; document the choice. Do not leave it undefined.

---

### 15. The `?wait=true` sync audit path and the 202-poll path create two divergent code paths through the most complex logic, doubling the correctness surface.

**Why it matters.** Domain 3 ships both a synchronous `?wait=true` (capped, 25s budget) and the primary 202+poll path through the *same* audit logic. But the sync path runs the audit *in the request transaction* (where `SET LOCAL app.tenant_id` is set by the request middleware), while the async worker runs it in a *worker-set* transaction. These two execution contexts have different tenant-context plumbing (finding #8), different timeout budgets, and different failure semantics (sync raises to the client; async writes `status=failed`). Two paths through the grounding/retry/verdict logic means bugs fixed in one can persist in the other, and the eval harness (Domain 2) only exercises the function-level logic, not both execution wrappers.

**Mitigation.** For MVP, **cut the sync path entirely** — it's a "convenience" that doubles the highest-risk surface. The dashboard can poll a 202 just as easily (Domain 3 even admits polling is trivially testable). If a sync quick-check is truly wanted post-MVP, implement it as the async path with server-side polling, so there is exactly one execution context. This is a *subtraction* that improves correctness — the right MVP move.

---

## Open risks in my domain (Completeness & Risk)

- **The three supersession models (#2) and the PK-type split (#1) are integration-blocking contradictions, not stylistic differences** — if the team builds domains in parallel without a reconciliation ADR first, retrieval correctness and RLS will both fail in ways that single-tenant/single-rule tests pass through silently.
- **The Pakistan-specific reality (Urdu/bilingual #5, "immediate effect" date ambiguity #4) is the home market's normal case, not an edge case** — the MVP can ship by *explicitly scoping it out and failing safe*, but if it ships pretending these don't exist, the demo on a real SECP gazette will produce garbage with a confident green checkmark.
- **Audit reproducibility is claimed but the retroactive-amendment staleness (#3) and dual sync/async paths (#15) mean stored verdicts can silently become wrong** — for a compliance product, a silently-flipped verdict is the reputational worst case and deserves the cheap staleness-flag mitigation before launch.
- **Connection-budget math across API + audit worker + ingestion cron (#11) is unowned** — no domain sums them against the Neon tier limit, and the cron-keeps-Neon-warm interaction quietly invalidates the cost model.
- **I could not verify any of this against real SECP/SBP documents or a running system** — extraction fidelity (Domain 4's own #1 risk), Urdu prevalence, ETag reuse behavior, and Neon connection ceilings are all asserted from general knowledge; the highest-leverage next step is ingesting 5-10 real gazettes before locking the schema.