# Runbook — Production Deploy (Neon + Render)

## One-time provisioning

### 1. Neon

1. Create a Neon project (Postgres 16), database `chronosguard`. The default
   role becomes `cg_owner` in our model — or create a dedicated `cg_owner`.
2. As the owner, run the runtime-role bootstrap (passwords from a secret
   manager — these never enter the repo):

   ```sql
   CREATE ROLE cg_app    LOGIN PASSWORD '<secret-app>';
   CREATE ROLE cg_worker LOGIN PASSWORD '<secret-worker>';
   ```

   Migration 0001 creates the roles `NOLOGIN` if absent and applies all
   grants — running this first simply attaches LOGIN.
3. Use the **direct** (non-pooled) connection host for all three URLs
   (`SET LOCAL` tenancy must share the transaction's physical connection;
   asyncpg's `statement_cache_size=0` is already set defensively).
4. Confirm plan retention covers your PITR window (rollback depends on it).

### 2. Render

1. New Blueprint → point at this repo → `infra/render.yaml`.
2. Fill the `sync: false` env vars: three database URLs, `OPENAI_API_KEY`,
   `SENTRY_DSN` (optional).
3. First deploy runs `alembic upgrade head` pre-deploy, then health-gates on
   `/readyz` before cutover.

### 3. Smoke test

```powershell
# operator machine, prod env vars in shell
uv run chronos jurisdictions add PK "Pakistan"
uv run chronos org create "FirstCustomer" --jurisdiction PK
uv run chronos keys create --org-id 1 --scopes audit   # store the printed key NOW
curl -H "X-API-Key: <key>" https://<service>/api/v1/me
```

## Routine deploys

Push to `main` → CI (lint, types, unit, integration+RLS, contract, migration
gate) → Render auto-deploy → pre-deploy migration → health-gated cutover.
Migrations are forward-only and expand/contract: never DROP something the
still-running version reads in the same deploy.

## Rollback

**Prod rollback = Neon PITR + redeploy the prior image. Never `alembic
downgrade` in prod** (downgrade scripts are local-dev hygiene only).

1. Render → service → Rollback to the last good deploy (image only).
2. If the bad deploy's migration wrote data you must discard:
   Neon → Restore → branch from timestamp *before* the deploy → promote.
3. Re-run the smoke test. Audit runs created in the lost window are gone —
   communicate to affected tenants; the queue is safe to re-trigger.

## Incident quick checks

| Symptom | First look |
|---|---|
| 503 on POST /audits | Circuit breaker open — check OpenAI status + `openai_call` error logs; it half-opens after 60s |
| readyz degraded | `database` check failing — Neon status, connection budget |
| Audits stuck `queued` | Worker logs (`job_failed`, reaper `jobs_reaped`); `chronos status --failed`; `chronos retry <id>` |
| Document missing from search | `chronos status --review` — quarantined? `chronos confirm <doc_id>` after review |
| Verdict disputed | `audit_runs` snapshot: `policy_text_snapshot`, `clauses_snapshot`, `retrieved_chunk_ids`, `as_of_date` reproduce exactly what the run saw; check `stale` flag |
