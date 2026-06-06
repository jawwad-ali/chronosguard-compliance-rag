# ChronosGuard Compliance — agent guide

Temporal Compliance RAG Engine. FastAPI backend in `apps/api` (src layout,
package `chronosguard`). **`docs/ARCHITECTURE.md` is the source of truth**;
deviations from `project-document.md` are recorded in its §12. Build plan +
acceptance gates: `docs/ROADMAP.md`. Ops: `docs/runbooks/`.

## Commands (run from `apps/api`)

```powershell
uv sync                  # deps (Python 3.12 via uv)
uv run poe up            # local Postgres+pgvector (docker compose, host port 5433)
uv run poe migrate       # alembic upgrade head (owner role)
uv run chronos seed      # idempotent 6-doc temporal fixture corpus + 2 orgs
uv run poe api           # uvicorn :8000 (in-process worker included)
uv run poe lint | types  # ruff / mypy strict (both must be clean)
uv run poe test          # unit lane only (no Docker, no network)
uv run pytest -q         # everything except eval (needs Docker Desktop)
uv run pytest -m eval    # golden-set quality lane (fakes; CG_EVAL_LIVE=1 for OpenAI)
```

## Hard rules (working agreements — docs/ROADMAP.md)

1. **One temporal predicate.** "In force on date X" lives ONLY in
   `retrieval/temporal.py::as_of_predicate`. Never inline a second copy.
2. **No stored `is_active`.** In-force is derived from DATE intervals
   `[effective_date, expiration_date)`. Supersession = close interval +
   lineage edge (`supersessions` is never in the hot query path).
3. **RLS discipline.** App role `cg_app` / worker `cg_worker` are never table
   owners; tenant context is `SET LOCAL` (transaction-scoped) only. The `rls`
   pytest lane is blocking — includes the worker INSERT path.
4. **CI never spends OpenAI money.** `FakeEmbeddings`/`FakeChat` in all test
   fixtures; real calls only in the manual eval lane.
5. **LLM output is never trusted for citations.** `citation`/`source_url`/
   `legal_rule_text` come from the DB by ref_id; quotes are ground-verified
   or the finding is dropped.
6. **Contract freeze.** API changes require `uv run chronos export-openapi`
   (snapshot in `packages/contracts/`); CI fails on silent drift.
7. **Migrations**: hand-written, named constraints (naming convention), RLS/
   HNSW/trigger DDL via `op.execute`. Drift gate = `alembic check` in tests.
   Prod rollback = Neon PITR, never `alembic downgrade`.

## Gotchas

- Local Postgres is on **5433** (5432 hosts an unrelated Odoo Postgres).
- `tests/conftest.py` owns the testcontainers harness; the session fixture
  proves migration reversibility every run. Integration tests share one DB —
  isolate new corpus writes under a fresh jurisdiction (ingestion uses `SG`)
  or the PK truth-table suite breaks.
- SQLModel + mypy strict: wrap column comparisons in `sqlmodel.col()`.
- `Identity(always=True)` PKs: never supply explicit ids in inserts.
- The in-process worker is lifespan-managed; tests disable it
  (`worker_enabled=False`) and drive `Worker.drain()` explicitly.
