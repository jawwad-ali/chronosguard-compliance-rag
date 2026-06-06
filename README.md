# ChronosGuard Compliance

**A "time machine" for regulations: it audits a company's internal policies against the law
that was actually in force on any given date — and proves every claim with a verified quote.**

[![CI](https://img.shields.io/badge/CI-GitHub_Actions-2088FF?style=flat-square&logo=githubactions&logoColor=white)](./.github/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-178_passing-brightgreen?style=flat-square)](apps/api/tests)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](apps/api/pyproject.toml)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-16-000?style=flat-square&logo=nextdotjs&logoColor=white)](apps/web)
[![PostgreSQL](https://img.shields.io/badge/Postgres-pgvector-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)
[![OpenAI](https://img.shields.io/badge/OpenAI-structured_outputs-412991?style=flat-square&logo=openai&logoColor=white)](apps/api/src/chronosguard/providers)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)

> This README doubles as an **interview walkthrough**. Read it top to bottom and you can
> answer "can you walk me through this project?" with confidence.

---

## The 30-second pitch

Companies in regulated industries (fintech, healthcare) write internal policies that must
follow the law. But the law keeps changing, and regulators publish changes as PDF documents —
not as an API. Over time, policies quietly drift out of compliance.

ChronosGuard reads those legal PDFs into a searchable database, remembers **when each rule
started and stopped being valid**, and uses AI to check a company's policy text against the
rules — clause by clause. Every violation it reports comes with an exact quote from the law,
verified by the server, so the AI can never invent a rule that doesn't exist.

---

## The problem it solves

Imagine a payment company, "PocketPay", whose policy says:

> *"PocketPay will hold user funds for up to 7 business days before clearing."*

- In **2024**, the regulator allowed holding funds for 7 business days. ✅ Compliant.
- In **June 2026**, an amendment cut the limit to **3 business days**. ❌ Now in violation —
  but nobody at PocketPay noticed, because the change was published in a PDF gazette.

This slow, silent mismatch is called **regulatory drift**. Catching it manually means a
compliance officer re-reading hundreds of pages after every legal change. ChronosGuard
automates exactly that job — and because it remembers *when* each rule applied, it can also
answer historical questions like *"were we compliant in January 2025?"* (useful for audits
and disputes).

---

## What the system does (the core loop)

1. **Ingest** — legal PDFs are downloaded, converted to text, split into sections, and
   stored with their validity dates ("in force from 1 June 2026, until further notice").
2. **Search in time** — given a question, a jurisdiction, and a date, it finds only the
   rules that were valid **on that date**. Expired and replaced rules never leak in.
3. **Audit** — a policy is split into clauses. For each clause, the relevant rules are
   retrieved and an AI model judges: violation, compliant, or "not enough law found".
4. **Prove it** — every finding must contain a word-for-word quote from the law. The server
   checks that the quote really exists in the source text. If it doesn't, the finding is
   thrown away. The AI cannot fabricate citations.

### See it work

The same policy, audited at two points in time, gets two different (and correct) answers:

```text
POST /api/v1/audits  { policy: "...hold user funds up to 7 business days...",
                       jurisdiction: "PK", as_of_date: "2026-06-06" }
→ verdict: VIOLATIONS_FOUND
  finding [HIGH]  Regulation 12-B(4) (as amended)
  quote: "…must settle transit funds within a strict maximum window
          of three (3) business days."
  fix:   Reduce the holding window to 3 business days.

Same request with as_of_date: "2025-01-01"
→ verdict: COMPLIANT        (the old 7-day rule applied back then)
```

---

## Architecture (the big picture)

```text
                ┌────────────────────────────────────────────┐
 Browser ─────▶ │  Next.js dashboard (apps/web)              │
                │  · API key kept in an httpOnly cookie      │
                │  · all calls go through a same-origin proxy│
                └───────────────────┬────────────────────────┘
                                    │
                ┌───────────────────▼────────────────────────┐
                │  FastAPI backend (apps/api)                │
                │  ├─ REST API (auth, audits, policies, search)
                │  └─ background worker (runs audits/ingestion)
                └───────────────────┬────────────────────────┘
                                    │
                ┌───────────────────▼────────────────────────┐
                │  PostgreSQL + pgvector                     │
                │  · legal documents + their validity dates  │
                │  · vector index for semantic search        │
                │  · row-level security for tenant isolation │
                │  · a jobs table that acts as the queue     │
                └───────────────────┬────────────────────────┘
                                    │
                              OpenAI API
                   (embeddings + structured AI verdicts)
```

Three moving parts, deliberately few:

- **One web app** — the dashboard people use.
- **One backend process** — the API *and* the background worker live in the same process
  (cheaper to host, simpler to operate; can be split later without code changes).
- **One database** — Postgres does triple duty: normal data, vector search (pgvector),
  and the job queue. No Redis, no separate vector database, no message broker.

---

## Technologies used — and why

| Technology | What it is | Why this one |
|---|---|---|
| **FastAPI (Python)** | Async web framework | Async fits a workload that mostly waits on the database and OpenAI; built-in request validation; auto-generated API docs |
| **PostgreSQL** | Relational database | One battle-tested store for everything; its Row-Level Security gives database-enforced tenant isolation |
| **pgvector** | Postgres extension for vector search | Semantic search *inside* the same database, so a single SQL query can combine "similar meaning" with "valid on this date" |
| **SQLModel + Alembic** | ORM + migrations | Typed models shared with the API schemas; every schema change is a reviewed, reversible migration |
| **OpenAI** | Embeddings + judging model | `text-embedding-3-small` for cheap semantic search; a small GPT model with *structured outputs* so answers always arrive as valid, typed JSON |
| **Next.js 16 + TypeScript** | Frontend framework | Server-side rendering, file-based routing, and server actions for the cookie-based login flow |
| **Tailwind CSS + shadcn/ui** | Styling + UI primitives | Accessible components re-themed into a custom design system (not default-looking) |
| **TanStack Query** | Frontend data layer | Caching, retries, and automatic polling for the "wait for the audit to finish" flow |
| **Docker + testcontainers** | Test infrastructure | Tests run against a real disposable Postgres — vector search and security rules can't be faked with SQLite |
| **uv, ruff, mypy (strict)** | Python tooling | Fast installs, one linter, and strict type checking from day one |

---

## How the main features work

### 1. The time machine (temporal model) — the heart of the project

- Every legal rule is stored with two dates: `effective_date` (when it started applying) and
  `expiration_date` (when it stopped; empty = still active).
- "What law applied on date X?" is then just a date comparison — simple, fast, and testable.
- When a new rule replaces an old one, the old rule is **never deleted**. Its end date is
  set instead. That keeps history intact, so audits about the past still work.
- There is exactly **one** function in the whole codebase that answers "in force on date X"
  — every feature (search, audits, the UI) calls it. One implementation means the logic can
  never quietly diverge.
- A table-driven test suite checks all the tricky edges: the exact start day counts, the
  exact end day doesn't, rules dated into the past ("retroactive") work, and unreviewed
  documents are invisible.

### 2. The AI audit with a lie detector (grounded RAG)

RAG means the AI **looks up real documents first** and answers only from them, instead of
guessing from memory. ChronosGuard adds three safety layers:

- **The AI never writes citations.** It can only point at an excerpt by its ID; the citation
  text and source link are filled in from the database. Inventing a source is impossible.
- **Quote checking.** Each finding must include a word-for-word quote. The server verifies
  the quote appears in the real text; otherwise the finding is silently dropped and counted
  (that counter is our "hallucination alarm").
- **Honest verdicts.** If no relevant law is found, the answer is "insufficient evidence" —
  **never** "compliant". A false green checkmark is the worst possible failure for a
  compliance tool.

### 3. Multi-tenancy enforced by the database (Row-Level Security)

- Many companies (tenants) share one database. Each one must never see another's data.
- Instead of trusting every developer to remember `WHERE tenant_id = ...` in every query,
  **Postgres itself filters rows**: each request sets its tenant ID on the connection, and
  security policies attached to the tables do the rest.
- It "fails closed": if the tenant ID is ever missing, queries return **zero rows** rather
  than everyone's rows.
- A dedicated, **blocking** test suite proves isolation — including the tricky background-
  worker path — by connecting as the real low-privilege database user.

### 4. Background jobs without extra infrastructure

- Audits take seconds (multiple AI calls), so the API answers immediately with
  "202 Accepted, here's your run ID" and the client polls for the result.
- The queue is just a Postgres table. A worker claims jobs with `FOR UPDATE SKIP LOCKED`
  (so two workers can never grab the same job), holds a time-limited "lease", and a reaper
  re-queues jobs whose worker crashed. Failed jobs retry up to 3 times.

### 5. Ingestion with a quarantine gate

- PDFs become Markdown, then get split along their legal structure (Part → Chapter →
  Section) so each stored chunk is a meaningful rule, not an arbitrary slice.
- Suspicious documents are **quarantined for human review** instead of entering search:
  scanned images (no extractable text), non-English text (Urdu gazettes are real in the
  target market — better refused than silently garbled), documents with no detectable
  structure, and text containing prompt-injection patterns ("ignore previous instructions…").
- Re-publishing a corrected PDF creates a **new version**; the old one leaves search but is
  kept, because past audits referenced it.

### 6. The frontend ("Gazette Ledger" design)

- A custom light theme built on a five-color palette where colors carry meaning: dark blue
  is "ink" (text), teal is "action" (buttons/links), and yellow → orange → red is the risk
  ladder (low → medium → high). Poppins font throughout.
- Signature touches: verdicts rendered as rubber **stamps**, the as-of date as a calendar
  leaf, findings as numbered ledger entries with a side-by-side view — *your policy* on the
  left, *the law in force* on the right.
- Every screen handles loading (skeletons), empty, and error (with retry) states.

---

## Request → response flow (one audit, end to end)

1. **Login**: the user pastes an org API key. A server action validates it against the
   backend and stores it in an **httpOnly cookie** — browser JavaScript can never read it.
2. **Create**: the dashboard POSTs to its own origin (`/api/cg/audits`). A tiny proxy route
   attaches the key from the cookie and forwards the call to FastAPI.
3. **Queue**: FastAPI checks the key (hash lookup), sets the tenant on the database
   connection, validates the body, snapshots the policy text into an `audit_runs` row, adds
   a row to the `jobs` table, and replies **202** with the run ID. Total: milliseconds.
4. **Work**: the background worker claims the job, sets the same tenant context, splits the
   policy into clauses, embeds them (one batched OpenAI call), and for each clause asks
   Postgres: *semantically similar AND valid on the as-of date AND confirmed*.
5. **Judge**: each clause + its retrieved excerpts go to the AI with a strict JSON schema.
   Replies are quote-checked; valid findings are saved with citations from the database.
6. **Verdict**: clause results roll up — any violation ⇒ `VIOLATIONS_FOUND`; any failed
   clause ⇒ `partial` (never falsely compliant); nothing relevant ⇒ `INSUFFICIENT_EVIDENCE`.
   Cost and token counts are saved on the run.
7. **Poll**: the dashboard re-fetches every 1.5 s until the run is finished, then renders
   the stamp, the coverage bar, and the findings ledger.

---

## Key decisions and trade-offs

| Decision | Why | Trade-off accepted |
|---|---|---|
| **Dates, not an `is_active` flag** | A stored "active" boolean goes stale the moment law changes; deriving validity from dates can't go stale | Slightly more complex queries |
| **Postgres as the job queue** | One less system to run, pay for, and monitor; `SKIP LOCKED` makes it safe | Job pickup is ~1 s, not instant — fine for audits that take seconds anyway |
| **202 + polling, not streaming** | A verdict must be quote-verified as a whole before anyone sees it; polling is trivial to build and test | Results appear ~1.5 s later than a streaming UI would show partials |
| **Fake AI providers in CI** | Tests cost $0, are deterministic, and never flake on OpenAI hiccups; real-model quality runs in a separate manual "eval" lane | The fakes must be designed carefully so tests still mean something |
| **Rule-based date extraction (not LLM)** | Legal phrases like "shall come into force on 1 July 2026" are regular enough for patterns; deterministic and free | Odd phrasings fall back to "publication date" — recorded honestly with a provenance label |
| **API key in an httpOnly cookie + server proxy** | The browser never holds the secret; XSS can't steal it; no CORS configuration at all | Every frontend call makes one extra same-origin hop |
| **Big integers as IDs (not UUIDs)** | Single database, single writer — UUIDs solve problems this system doesn't have; ints are smaller and index-friendlier | IDs are guessable — acceptable because RLS makes other tenants' rows invisible anyway |
| **Soft scope cuts, recorded** | Things like OCR for scanned PDFs and Urdu support were *deliberately* deferred — each with a written "bring it back when X" trigger | The MVP refuses some inputs (safely) instead of handling them badly |

---

## Challenges faced — and how they were solved

1. **The background worker couldn't write its own results.**
   Row-Level Security blocked the worker's inserts, because a worker doesn't go through the
   normal login flow, so it had no tenant context. *Fix:* the job queue itself is a global
   (non-tenant) table that carries the tenant ID; the worker reads it and sets the tenant
   context per job, inside that job's transaction. A dedicated test now proves the worker
   path writes correctly — and that it's *rejected* without context.

2. **Three "experts" designed the same feature three incompatible ways.**
   During the design phase (run as parallel specialist designs plus adversarial reviews),
   the "rule replaced by rule" mechanism came back in three conflicting versions. The review
   step caught it before any code existed. *Lesson worth telling:* design reviews are
   cheapest before the first migration; the fix was one written decision everyone built on.

3. **Testing AI behavior without paying for AI.**
   *Fix:* fake providers with real behavior. The fake embedder hashes words into vectors, so
   texts sharing vocabulary genuinely score as similar — ranking tests mean something. The
   fake judge applies a simple rule ("policy allows N days, law allows fewer ⇒ violation")
   and is scriptable per test, which made it possible to test the quote-checker by forcing
   the fake to "lie".

4. **A one-line text splitter bug flipped a verdict.**
   The clause splitter merged short paragraphs into their neighbor; the famous 7-day clause
   (74 characters) vanished into the clause beside it, retrieval matched the wrong rule, and
   the end-to-end test failed with COMPLIANT instead of VIOLATIONS_FOUND. *Fix:* lower the
   merge threshold and make merged fragments adopt the *substantial* section's heading. The
   takeaway: in RAG systems, boring text-processing bugs can change answers — end-to-end
   tests with known expected verdicts are what catch them.

5. **Environment landmines.**
   Port 5432 was already taken by another local Postgres (moved to 5433); a UI library
   updated its API under the generated component (one renamed key); Windows PowerShell
   silently drops the `Cookie` header in test requests (switched to a proper cookie
   session). None are glamorous — all are the daily reality of shipping.

---

## Possible future improvements

- **Live deployment** — config and runbooks for Neon (Postgres) + Render already exist in
  `infra/` and `docs/runbooks/`; it's a credentials-and-click task.
- **OCR for scanned gazettes** and **Urdu/bilingual support** — currently quarantined
  safely; both have written re-activation triggers.
- **Automatic supersession suggestions** — the system already *detects* "this circular
  supersedes Circular 5 of 2019" and suggests links; confirming them stays human for now
  because a wrong link silently removes valid law from audits.
- **n8n nightly monitor** — the admin ingestion endpoint (the "n8n contract") is live;
  the watcher workflow that polls regulator websites is the natural next step.
- **Hybrid search (full-text + vector)** and a **re-ranking model** — behind an existing
  seam, waiting for evaluation numbers that justify them.
- **Bigger golden-test set** — the evaluation harness (retrieval recall, verdict accuracy,
  hallucination counter) exists; growing the labeled examples raises the quality bar.

---

## Quickstart (local)

Prereqs: [uv](https://docs.astral.sh/uv/), Node 20+, Docker Desktop.

```powershell
# Backend
cd apps/api
uv sync ; copy .env.example .env
uv run poe up          # Postgres 16 + pgvector (host port 5433)
uv run poe migrate     # apply migrations
uv run chronos seed    # demo corpus + demo orgs
uv run chronos keys create --org-id 1 --scopes audit   # copy the printed key!
uv run poe api         # http://localhost:8000/docs

# Frontend (second terminal)
cd apps/web
npm install ; copy .env.local.example .env.local
npm run dev            # http://localhost:3000 → paste the key
```

Test lanes (backend): `uv run poe test` (unit, no Docker) · `uv run pytest -q` (everything:
integration, security, contract) · `uv run pytest -m eval` (AI-quality lane, runs on fakes
for free).

## Project layout

```text
apps/api/            FastAPI backend — the engine (src/chronosguard)
apps/web/            Next.js dashboard — the Gazette Ledger UI
packages/contracts/  Frozen OpenAPI schema (the API↔UI contract, drift-tested in CI)
infra/               docker-compose (local DB), render.yaml (deploy blueprint)
docs/                ARCHITECTURE.md · ROADMAP.md · runbooks/
```

## Numbers worth remembering (for the interview)

- **178 backend tests** across 5 lanes — unit, integration (real Postgres in Docker),
  security (cross-tenant isolation, *blocking*), contract (API schema freeze), and eval
  (AI quality). CI spends **$0** on AI.
- **6 migrations**, every one proven reversible on every test run.
- **~$0.03 per audit** in OpenAI costs; **~$55–110/month** projected hosting.
- **11 frontend routes**, 13 reusable brand components, one custom design system.

## License & author

MIT — see [LICENSE](LICENSE).

Built by **Ali Jawwad** ([@jawwad-ali](https://github.com/jawwad-ali)). If this repo's
temporal-RAG or row-level-security patterns helped you, a ⭐ is appreciated.
