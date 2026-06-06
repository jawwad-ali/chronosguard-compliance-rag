I have the full spec. Now I'll write my domain design directly as the return value.

# Retrieval & RAG Pipeline — Domain Design

Owns the path from `policy_text` submission to structured `violations`. Decisions below are pinned; rationale is one line each.

## 1. Pipeline overview

```
policy_text
  → segment into auditable units (clauses)          [§5]
  → embed each clause (batched)                      [§6]
  → SQL candidate filter: jurisdiction + as-of + is_active   [§2]
  → ANN order by cosine_distance, LIMIT k            [§3]
  → optional FTS citation boost (deferred mostly)    [§4]
  → assemble grounded context per clause             [§7]
  → GPT Structured Outputs verdict (strict)          [§8]
  → quote-grounding verification + confidence        [§9]
  → AuditResponse (complete JSON, no streaming MVP)  [§10]
```

Stage boundaries map to module files (see §11 tree). Each stage is a pure-ish async function taking typed inputs, returning typed outputs, so the eval harness (§12) can drive any stage in isolation.

## 2. Temporal correctness — the load-bearing predicate

This is the product differentiator, so it lives in **one** reusable SQLAlchemy filter helper, never inlined ad hoc. The spec's `RegulatoryChunk` has `effective_date`, `expiration_date`, `is_active`. I deliberately do **not** trust `is_active` alone for point-in-time correctness — it is a *current-state denormalization* maintained by ingestion, useful only for the "today" fast path and as a sanity cross-check.

### 2.1 As-of semantics (the canonical filter)

```python
# app/retrieval/temporal.py
from datetime import datetime
from sqlalchemy import or_
from app.models import RegulatoryChunk as RC

def as_of_predicate(jurisdiction: str, as_of: datetime):
    """Rules in force in `jurisdiction` at instant `as_of`. Date-driven, NOT is_active."""
    return (
        (RC.jurisdiction == jurisdiction)
        & (RC.effective_date <= as_of)
        & or_(RC.expiration_date.is_(None), RC.expiration_date > as_of)
        & or_(RC.superseded_at.is_(None), RC.superseded_at > as_of)
    )
```

### 2.2 Required schema additions (flagged to DB-schema owner)

The spec's model is *insufficient for reproducible point-in-time audit*. I require three additions; rationale each:

| Column | Type | Why |
|---|---|---|
| `superseded_at` | `timestamptz NULL` | An amendment publishing on date D supersedes the prior chunk **at D**, not "now". A point-in-time audit for a date before D must still see the old rule. `is_active` cannot express this. |
| `superseded_by_chunk_id` | `int NULL FK` | Audit trail / "what replaced this" in the diff UI. |
| `content_hash` | `text NOT NULL` | Cheap idempotent re-ingest dedup + quote-grounding anchor (§9). |

`is_active` is kept but redefined as `expiration_date IS NULL AND superseded_at IS NULL` — derived, used only for the index partial-predicate and an optional fast path when `as_of` is "now".

**Bitemporality is DEFERRED (post-MVP).** We model *valid time* (when a rule is in force) but not *transaction time* (when we learned of it). If a regulator backdates an SRO and we ingest it late, a re-run of an old audit can change. Accepted for MVP; documented in §13. The hook is already there: add `knowledge_date`/`recorded_at` later without touching the query shape.

### 2.3 `as_of` resolution rule

```
as_of = request.target_date or now()   # tz-aware UTC; reject naive datetimes at the API boundary
```

Stored on the `AuditRun` row (DB owner's table) so an audit is **reproducible**: re-running with the same `(policy_text, jurisdiction, as_of)` against an unchanged corpus yields the same candidate set. This is the reproducibility contract.

### 2.4 Zero-candidate policy (decided)

Zero candidates after the temporal filter is **not** "compliant" — it is "no applicable law retrieved". The spec's `return AuditResponse(is_compliant=True, ...)` is a correctness bug I am overriding. We return a first-class `INSUFFICIENT_EVIDENCE` verdict at the run level (`status="no_corpus"`), never a false "you're compliant". Silent false-negatives are the worst failure mode in a compliance tool.

## 3. ANN search parameters (decided)

- **Distance metric: cosine.** `text-embedding-3-small` vectors are normalized; cosine is the standard and matches the spec's `cosine_distance`. Index: `vector_cosine_ops`.
- **Index: HNSW**, not IVFFlat. `CREATE INDEX ... USING hnsw (embedding vector_cosine_ops)`. HNSW gives better recall at low latency without a training step, and handles the incrementally-growing global corpus gracefully. `ef_search` set per-session (`SET LOCAL hnsw.ef_search = 80`) — tuned in eval. *(DB owner provisions the index; I own the parameter values.)*
- **k = 8 per clause** (over-retrieve from ANN at `k_ann = 24`, then trim — see threshold). Rationale: legal violations often hinge on 1–2 rules; 8 gives the LLM enough to find the relevant rule plus near-misses without blowing the token budget.
- **Similarity threshold: soft, not hard.** Cosine *distance* cutoff `0.55` (≈ similarity ≥ 0.45) to drop obvious junk, but we **always** pass the top candidate that survives the temporal filter even if above threshold, tagging context as `weak_match=true`. Hard thresholds silently hide rules; we'd rather let the LLM see a weak match and return `INSUFFICIENT_EVIDENCE` than retrieve nothing. Threshold value is an **eval-tuned knob**, not a guess.
- **On the temporal filter being the inner predicate:** the `WHERE` runs as a pre-filter to the HNSW scan. With pgvector, a restrictive metadata filter can force iterative scanning; for MVP corpus size (thousands of chunks per jurisdiction) this is fine. If recall degrades at scale, the upgrade path is a **partial HNSW index per active set** or filtered-search tuning — DEFERRED, noted to DB owner.

## 4. Hybrid search decision (decided)

**MVP = vector ANN + a narrow exact-citation lookup. Full FTS is DEFERRED.**

Legal text has two distinct match needs:
1. **Semantic** ("holds funds 7 days" ↔ "settle within 3 business days") → vector. Primary path.
2. **Exact symbol** (a policy that names "Section 12-B" or a defined term) → exact match.

For (2), MVP ships a **deterministic citation extractor + ILIKE lookup on `legal_citation`**, run *in addition to* vector retrieval and merged into candidates:

```python
# regex over policy clause for "Section 12-B", "Reg 4(a)", "Circular No. 7 of 2025"
cites = extract_citations(clause_text)
if cites:
    rows += exact_citation_lookup(cites, as_of_predicate(...))  # ILIKE legal_citation
```

Why not Postgres FTS/`tsvector` now: it adds a generated column, a GIN index, a ranking-fusion step (RRF), and a tokenizer config — real cost for marginal MVP gain over "vector covers semantics, regex covers the handful of citation cases". **FTS + Reciprocal Rank Fusion is DEFERRED (post-MVP)**, with the merge point already abstracted (`merge_candidates()`) so adding a third source is additive.

**Reranker (cross-encoder / LLM rerank): DEFERRED.** k=8 is small enough that the audit LLM itself acts as the final relevance filter. Revisit only if eval shows precision problems at k.

## 5. Policy-side chunking — the unit of audit (decided)

**MVP unit of audit = the clause (paragraph-level segment), not the whole document.**

An org policy is decomposed deterministically (no LLM) into clauses:

```python
# app/retrieval/policy_split.py
def split_policy(text: str) -> list[PolicyClause]:
    # 1. split on blank lines / markdown headings / numbered list items (1., a), (i))
    # 2. merge runts (< MIN_CHARS=120) into neighbour
    # 3. hard-cap at MAX_CHARS≈1500 (~400 tokens); over-long → sentence-window split
    ...
```

Rationale:
- **Auditability & citation fidelity:** a violation points at *one* offending clause (`PolicyClause.id`, char offsets), which the diff UI highlights — matches the spec's split-view requirement.
- **Retrieval quality:** embedding a whole policy averages out the signal; per-clause embeddings retrieve sharply.
- **Cost control:** clauses are audited concurrently with bounded fan-out (`asyncio.Semaphore`, default 5).

Whole-document audit is **DEFERRED**; clause-level composes up to a document verdict (`is_compliant = no clause has a HIGH/MEDIUM violation`).

`PolicyClause` is an in-memory/ephemeral structure for MVP (we don't persist org policy text beyond the audit run unless the DB owner's `AuditRun` stores it for reproducibility — recommend storing the clause array as JSONB on the run for replay).

## 6. Embedding provider abstraction (decided)

Thin wrapper over OpenAI; the rest of the pipeline never imports `openai` directly.

```python
# app/providers/embeddings.py
class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

class OpenAIEmbeddings:
    model = "text-embedding-3-small"  # 1536-dim, locked
    async def embed(self, texts: list[str]) -> list[list[float]]:
        # batch up to 96 inputs/call; tenacity retry (§8.3); 15s timeout
```

Clause embeddings are **batched in one API call** per audit (all clauses at once), cutting latency and cost. Query and corpus use the *same* model — non-negotiable for cosine validity.

## 7. Context assembly & prompt structure

Per clause, assemble a bounded context block. **Token budget: 6k tokens of retrieved context** per clause call (well under model limits, keeps cost predictable). Candidates are added in ascending-distance order until budget hit; never split a chunk mid-text (drop whole chunks).

Citation fidelity: every chunk enters context with a stable **`ref_id`** the LLM must echo back. The LLM never sees DB primary keys directly used for trust; it sees `ref_id` and we map back server-side.

```
SYSTEM:
You are a regulatory compliance auditor. You audit ONE internal policy clause
against ONLY the regulatory excerpts provided. Rules:
- Use ONLY the provided excerpts. Do not rely on outside knowledge of the law.
- Every violation MUST quote verbatim text from exactly one excerpt and name its ref_id.
- If the excerpts do not contain a rule that clearly governs the clause,
  return verdict INSUFFICIENT_EVIDENCE.
- A rule that is merely topically related but not violated is NOT a violation.

USER:
[AS_OF DATE]: 2026-06-06    [JURISDICTION]: PK

[REGULATORY EXCERPTS]
<ref_id=R1 | citation="Section 12-B(4)(a)" | source="SECP SRO 1234(I)/2026">
All retail digital accounts must settle transit funds within 3 business days.
</ref_id=R1>
<ref_id=R2 | ...>
...
</ref_id=R2>

[INTERNAL POLICY CLAUSE]
"PocketPay will hold user funds for up to 7 business days before clearing."
```

The `[AS_OF DATE]` is injected so the model never reasons about "current" law — it reasons as-of the audit date. `ref_id → {chunk_id, source_url, citation, content}` mapping is held server-side and stitched into the final `PolicyViolation`, so **citation/source_url come from the DB, never from the LLM** (the LLM cannot fabricate a URL).

## 8. OpenAI Structured Outputs — verdict contract

### 8.1 Model & params (decided)

- **Model: `gpt-4o-mini`** for MVP. Rationale: per-clause audit is a bounded, grounded judgment over short context; mini is ~15–20× cheaper than 4o/larger reasoning models and accurate enough *because* we constrain it with strict grounding + quote verification. Escalation hook: route clauses flagged `weak_match` or `HIGH` risk to a stronger model — DEFERRED.
- **`temperature = 0`** — determinism aids reproducibility and eval stability.
- **`response_format` = strict Structured Outputs** (`response_format=ClauseVerdict`, `strict=True`) — guarantees schema-valid JSON, eliminates the spec's fragile `json_object` mode and manual parsing.
- **Cost estimate:** ~2.5k input + ~300 output tokens/clause. At gpt-4o-mini pricing (~$0.15/$0.60 per 1M tok) ≈ **$0.0006/clause**. A 40-clause policy ≈ **$0.025/audit** plus ~$0.00002 embeddings. Negligible — leaves room to escalate hot clauses later.

*(Pricing/model specifics are from training knowledge; the AI-stack owner should confirm current model IDs/prices against the API skill before locking.)*

### 8.2 The strict schema (Pydantic)

```python
# app/audit/schema.py
from enum import Enum
from pydantic import BaseModel, Field

class Verdict(str, Enum):
    VIOLATION = "VIOLATION"
    COMPLIANT = "COMPLIANT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

class RiskLevel(str, Enum):
    HIGH = "HIGH"; MEDIUM = "MEDIUM"; LOW = "LOW"

class ClauseFinding(BaseModel):
    ref_id: str = Field(description="ref_id of the single excerpt this finding is grounded in")
    grounding_quote: str = Field(description="verbatim span copied from that excerpt")
    legal_rule_summary: str
    risk_level: RiskLevel
    rationale: str
    suggested_fix: str

class ClauseVerdict(BaseModel):
    verdict: Verdict
    findings: list[ClauseFinding]  # empty unless verdict == VIOLATION
    confidence: float = Field(ge=0.0, le=1.0)
```

The public `PolicyViolation` (spec contract) is **assembled server-side** by joining `ClauseFinding.ref_id` back to DB: `citation`, `source_url`, `legal_rule_text` come from the chunk row; `offending_policy_text` comes from the `PolicyClause`. This keeps the spec's response shape while making fabrication structurally impossible.

### 8.3 Retry / backoff / timeout (decided)

- **Per-call timeout: 30s.** Total audit budget governed by clause concurrency, not a single wall clock.
- **Retry: `tenacity`**, 3 attempts, exponential backoff (1s→2s→4s) + jitter, retry only on `RateLimitError`, `APITimeoutError`, `APIConnectionError`, 5xx. Never retry on schema/validation errors.
- **Idempotency:** clause audit is pure given `(clause, context, model, as_of)`; safe to retry.
- **Failure handling:** a clause whose LLM call exhausts retries is marked `status="error"` in results, never silently dropped or treated as compliant.

## 9. Hallucination defenses (decided)

Three layers, all server-side and cheap:

1. **Quote-grounding verification (hard gate).** For every `ClauseFinding`, verify `grounding_quote` actually occurs in the cited excerpt's text. Normalize whitespace/case, then check substring; allow a fuzzy fallback (`rapidfuzz` ratio ≥ 0.92) for minor punctuation drift. **If the quote isn't found, the finding is dropped** and the clause is downgraded to `INSUFFICIENT_EVIDENCE` (or remaining valid findings stand). This catches the classic "LLM invents a rule" failure. `content_hash`/exact text from the DB is the source of truth.
2. **`INSUFFICIENT_EVIDENCE` as a first-class verdict** (not an error, not "compliant"). Drives the UI to say "no governing rule found in corpus" rather than a false green check.
3. **Confidence + weak-match propagation.** `confidence` from the model, combined with retrieval `weak_match` flag, yields a `needs_review` boolean surfaced to the UI. Low-confidence VIOLATIONs are flagged, not suppressed.

`source_url` and `citation` are never model-authored (§7), so those fields cannot hallucinate by construction.

## 10. Streaming decision (decided)

**MVP returns complete JSON. No SSE.** The spec mentions `StreamingResponse`, but:
- The verdict is a structured object consumed for a diff UI — partial JSON is not usefully renderable and complicates strict-schema validation + quote-grounding (both need the complete object).
- Per-clause fan-out already bounds latency; a 40-clause audit completes in a few seconds.

**What we ship instead:** the audit can run **async with a job model** if latency grows — `POST /audit` returns `202 + run_id`, client polls `GET /audit/{run_id}`. For MVP, synchronous complete `AuditResponse` is fine. **Per-clause SSE progress (`event: clause_done`) is DEFERRED**, with the pipeline already emitting per-clause results that an SSE generator could wrap later. Endpoint contract documented for the Next.js owner so the UI can adopt polling/SSE without a response-shape change.

## 11. Module layout (my domain)

```
app/
  retrieval/
    policy_split.py      # split_policy() → list[PolicyClause]
    temporal.py          # as_of_predicate(), resolve_as_of()
    candidates.py        # vector_search(), exact_citation_lookup(), merge_candidates()
    citations.py         # extract_citations() regex
  providers/
    embeddings.py        # EmbeddingProvider protocol + OpenAIEmbeddings
    llm.py               # ChatProvider protocol + OpenAIChat (structured outputs)
  audit/
    schema.py            # Verdict/ClauseVerdict/ClauseFinding pydantic
    prompt.py            # build_context(), render_prompt(), token budgeting
    grounding.py         # verify_quote(), downgrade logic
    pipeline.py          # orchestrate: split→embed→retrieve→audit→verify→assemble
    service.py           # audit endpoint glue, fan-out concurrency, AuditRun persistence hook
eval/
  golden/                # see §12
  test_retrieval_eval.py
  test_audit_eval.py
```

Key interface signatures:

```python
async def audit_policy(req: ComplianceAuditRequest, db: AsyncSession,
                       emb: EmbeddingProvider, llm: ChatProvider) -> AuditResponse: ...

async def vector_search(clause_vec: list[float], jurisdiction: str, as_of: datetime,
                        db: AsyncSession, k_ann: int = 24) -> list[Candidate]: ...

async def audit_clause(clause: PolicyClause, candidates: list[Candidate],
                       as_of: datetime, llm: ChatProvider) -> ClauseResult: ...
```

## 12. Evaluation harness (lean but real)

**Golden dataset shape** (`eval/golden/`, JSONL, version-controlled, seeded into a Neon test branch):

```jsonc
// rules.jsonl — fixed corpus subset with known temporal facts
{"chunk_key":"R1","jurisdiction":"PK","legal_citation":"Sec 12-B(4)(a)",
 "content":"...settle within 3 business days...","effective_date":"2026-01-01",
 "expiration_date":null,"superseded_at":null}

// cases.jsonl — labeled policy→expected
{"id":"c001","jurisdiction":"PK","as_of":"2026-06-06",
 "policy_text":"hold user funds up to 7 business days...",
 "expected_chunk_keys":["R1"],            // retrieval ground truth
 "expected_verdict":"VIOLATION",
 "expected_risk":"HIGH"}

// temporal cases — same policy, different as_of, different expected rule
{"id":"c002","as_of":"2025-06-01","expected_chunk_keys":["R0_superseded"], ...}
```

**Retrieval metrics:** `recall@k` and `MRR` on `expected_chunk_keys` (the core "did we surface the right rule" number). Plus a dedicated **temporal-correctness assertion**: for cases that differ only by `as_of`, assert superseded chunks are *absent* and the in-force chunk is *present* — this directly tests the differentiator.

**Audit-quality metrics:** verdict accuracy (confusion matrix over the 3 verdicts), VIOLATION precision/recall (false-positive rate is the headline — over-flagging erodes trust), risk-level agreement, and **grounding pass rate** (% findings whose quote verified — a hallucination canary).

**CI integration:** two tiers.
- **Offline tier (every PR, no API cost):** retrieval metrics against a pre-embedded fixture corpus (cached vectors committed as a small `.npy`/JSONL so embeddings aren't recomputed); grounding/verdict logic tested against **recorded LLM responses** (fixtures), no live calls. Fast, deterministic, free.
- **Live tier (nightly / manual / pre-release, gated on `OPENAI_API_KEY`):** runs the real models over the golden cases, asserts `recall@8 ≥ 0.9` and `verdict_accuracy ≥ 0.85` (thresholds are starting gates, tuned). Posts metrics; fails the nightly job on regression.

`pytest + anyio`; markers `@pytest.mark.eval_offline` / `@pytest.mark.eval_live`. Keeps PR CI fast while still exercising real quality on a schedule.

## Open risks in my domain

- **Filtered-ANN recall at scale.** A restrictive temporal `WHERE` over a growing global HNSW index can degrade recall/latency; MVP corpus is small enough, but the partial-index/iterative-scan upgrade is unproven for us — needs an eval gate before the corpus grows large.
- **No transaction-time (bitemporal) modeling.** Backdated/late-ingested regulations make a past audit's re-run non-stable. Accepted for MVP; could surprise an auditor expecting byte-identical replay. Mitigated only by storing `as_of` + clause snapshot on the run.
- **Quote-grounding fuzz threshold is heuristic.** Too strict drops valid findings (over-conservative `INSUFFICIENT_EVIDENCE`); too loose lets paraphrased "quotes" pass. The 0.92 ratio is a guess until the eval set is large enough to tune it.
- **Deterministic policy splitter on messy real policies.** Pasted policy text without clean structure may split poorly, producing runt or over-merged clauses that hurt retrieval precision. Needs real-document fixtures in the eval set early.
- **gpt-4o-mini ceiling on subtle legal reasoning.** Mini may miss nuanced violations (conditional/cross-referenced rules) that a stronger model catches; the escalation path exists but is deferred, so MVP false-negative rate on hard cases is unmeasured until the live eval tier accrues cases.