"""The job worker: claim → per-job tenant context → execute → settle.

Design (docs/ARCHITECTURE.md §3.6): the queue is GLOBAL (no RLS) precisely so
the worker can see jobs across tenants; tenant isolation re-engages the moment
work starts — each job runs in a fresh transaction with SET LOCAL tenant
context, so RLS governs every tenant-scoped read/write the job performs.
Claiming uses FOR UPDATE SKIP LOCKED (safe for N workers); the lease + reaper
recover jobs orphaned by a crashed/redeployed instance.
"""

import asyncio
import contextlib
import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from chronosguard.audit.service import execute_audit_run
from chronosguard.ingestion.fetch import fetch_document
from chronosguard.ingestion.service import IngestHints, ingest_bytes, ingest_markdown
from chronosguard.models import JobKind, RunStatus
from chronosguard.providers.base import ChatProvider, EmbeddingProvider

logger = structlog.get_logger(__name__)

LEASE_TIMEOUT = dt.timedelta(minutes=15)

_CLAIM_SQL = text(
    """
    UPDATE jobs
    SET status = 'running', locked_at = now(), locked_by = :worker, attempts = attempts + 1
    WHERE id = (
        SELECT id FROM jobs
        WHERE status = 'queued'
        ORDER BY created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    RETURNING id, kind, ref_id, tenant_id, attempts, max_attempts, payload
    """
)

_SETTLE_SQL = text(
    "UPDATE jobs SET status = :status, error = :error, locked_at = NULL, locked_by = NULL "
    "WHERE id = :job_id"
)

_REQUEUE_SQL = text(
    "UPDATE jobs SET status = 'queued', locked_at = NULL, locked_by = NULL, error = :error "
    "WHERE id = :job_id"
)

_REAP_SQL = text(
    """
    UPDATE jobs
    SET status = CASE WHEN attempts >= max_attempts THEN 'failed' ELSE 'queued' END,
        error = COALESCE(error, 'lease expired'),
        locked_at = NULL, locked_by = NULL
    WHERE status = 'running'
      AND locked_at < now() - make_interval(secs => :lease_seconds)
    RETURNING id
    """
)


@dataclass(frozen=True)
class ClaimedJob:
    id: int
    kind: str
    ref_id: int | None
    tenant_id: int | None
    attempts: int
    max_attempts: int
    payload: dict[str, Any]


class Worker:
    def __init__(
        self,
        engine: AsyncEngine,
        embedder: EmbeddingProvider,
        chat: ChatProvider,
        *,
        name: str = "worker-1",
        poll_seconds: float = 1.0,
    ) -> None:
        self._maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        self._embedder = embedder
        self._chat = chat
        self.name = name
        self.poll_seconds = poll_seconds

    async def claim(self) -> ClaimedJob | None:
        async with self._maker() as session:
            row = (await session.execute(_CLAIM_SQL, {"worker": self.name})).mappings().first()
            await session.commit()
        if row is None:
            return None
        return ClaimedJob(
            id=row["id"],
            kind=row["kind"],
            ref_id=row["ref_id"],
            tenant_id=row["tenant_id"],
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            payload=row["payload"] or {},
        )

    async def _execute(self, job: ClaimedJob) -> None:
        if job.kind == JobKind.AUDIT.value:
            await self._execute_audit(job)
        elif job.kind == JobKind.INGEST.value:
            await self._execute_ingest(job)
        else:
            msg = f"Unknown job kind: {job.kind}"
            raise ValueError(msg)

    async def _execute_ingest(self, job: ClaimedJob) -> None:
        """Global-corpus work — tenant-agnostic by design (no tenant context)."""
        payload = job.payload
        hints = IngestHints(
            source_url=payload["source_url"],
            title=payload["title"],
            issuing_body=payload["issuing_body"],
            document_type=payload["document_type"],
            jurisdiction=payload["jurisdiction"],
            published_date=dt.date.fromisoformat(payload["published_date"]),
            source_etag=payload.get("source_etag"),
        )
        async with self._maker() as session:
            if "file_path" in payload:  # CLI/dev path: local file, .md or .pdf
                path = Path(payload["file_path"])
                if path.suffix.lower() == ".md":
                    markdown = await asyncio.to_thread(path.read_text, encoding="utf-8")
                    outcome = await ingest_markdown(
                        session, self._embedder, markdown=markdown, hints=hints
                    )
                else:
                    content = await asyncio.to_thread(path.read_bytes)
                    outcome = await ingest_bytes(
                        session, self._embedder, content=content, hints=hints
                    )
            else:
                fetched = await fetch_document(payload["source_url"])
                outcome = await ingest_bytes(
                    session,
                    self._embedder,
                    content=fetched.content,
                    hints=IngestHints(**{**hints.__dict__, "source_etag": fetched.etag}),
                )
            # Link the job to the produced document for the n8n status poll.
            await session.execute(
                text("UPDATE jobs SET ref_id = :doc_id WHERE id = :job_id"),
                {"doc_id": outcome.document_id, "job_id": job.id},
            )
            await session.commit()

    async def _execute_audit(self, job: ClaimedJob) -> None:
        if job.ref_id is None or job.tenant_id is None:
            msg = "Audit job missing ref_id/tenant_id"
            raise ValueError(msg)
        async with self._maker() as session:
            # One transaction per job: tenant context lives and dies with it.
            await session.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": str(job.tenant_id)},
            )
            await execute_audit_run(session, job.ref_id, embedder=self._embedder, chat=self._chat)
            await session.commit()

    async def _settle(self, job: ClaimedJob, *, error: Exception | None) -> None:
        async with self._maker() as session:
            if error is None:
                await session.execute(
                    _SETTLE_SQL, {"status": "succeeded", "error": None, "job_id": job.id}
                )
            elif job.attempts < job.max_attempts:
                await session.execute(
                    _REQUEUE_SQL, {"error": type(error).__name__, "job_id": job.id}
                )
            else:
                await session.execute(
                    _SETTLE_SQL,
                    {"status": "failed", "error": type(error).__name__, "job_id": job.id},
                )
                await self._mark_run_failed(session, job)
            await session.commit()

    async def _mark_run_failed(self, session: AsyncSession, job: ClaimedJob) -> None:
        """Terminal job failure ⇒ the run must not stay queued/running forever."""
        if job.kind != JobKind.AUDIT.value or job.ref_id is None or job.tenant_id is None:
            return
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(job.tenant_id)},
        )
        await session.execute(
            text(
                "UPDATE audit_runs SET status = :failed, error = 'job retries exhausted', "
                "finished_at = now() WHERE id = :run_id AND status IN ('queued', 'running')"
            ),
            {"failed": RunStatus.FAILED.value, "run_id": job.ref_id},
        )

    async def process_one(self) -> bool:
        """Claim and process a single job. Returns False when the queue is empty."""
        job = await self.claim()
        if job is None:
            return False
        log = logger.bind(job_id=job.id, kind=job.kind, attempt=job.attempts)
        try:
            await self._execute(job)
        except Exception as exc:
            log.exception("job_failed")
            await self._settle(job, error=exc)
        else:
            log.info("job_succeeded")
            await self._settle(job, error=None)
        return True

    async def drain(self, *, max_jobs: int | None = None) -> int:
        processed = 0
        while max_jobs is None or processed < max_jobs:
            if not await self.process_one():
                break
            processed += 1
        return processed

    async def reap(self) -> int:
        """Recover jobs orphaned by a crashed worker (expired lease)."""
        async with self._maker() as session:
            rows = (
                await session.execute(_REAP_SQL, {"lease_seconds": LEASE_TIMEOUT.total_seconds()})
            ).fetchall()
            await session.commit()
        if rows:
            logger.warning("jobs_reaped", count=len(rows), job_ids=[row[0] for row in rows])
        return len(rows)

    async def run_forever(self, stop: asyncio.Event) -> None:
        await self.reap()  # startup recovery
        last_reap = dt.datetime.now(dt.UTC)
        while not stop.is_set():
            try:
                worked = await self.process_one()
            except Exception:
                logger.exception("worker_loop_error")
                worked = False
            if dt.datetime.now(dt.UTC) - last_reap > dt.timedelta(minutes=5):
                await self.reap()
                last_reap = dt.datetime.now(dt.UTC)
            if not worked:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=self.poll_seconds)
