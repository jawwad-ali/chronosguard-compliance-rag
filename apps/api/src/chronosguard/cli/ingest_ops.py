"""Operator ingestion commands (worker-role engine; corpus is tenant-agnostic)."""

import datetime as dt
import json
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from chronosguard.core.config import get_settings
from chronosguard.ingestion.service import embed_pending_chunks
from chronosguard.ingestion.supersession import (
    SupersedeReport,
    confirm_document,
    confirm_supersession,
)
from chronosguard.models import JobKind
from chronosguard.providers import get_chat_provider, get_embedding_provider
from chronosguard.worker.runner import Worker


def _worker_engine() -> AsyncEngine:
    return create_async_engine(
        get_settings().database_url_worker,
        poolclass=NullPool,
        connect_args={"statement_cache_size": 0},
    )


def _owner_engine() -> AsyncEngine:
    """Operator/maintenance channel: confirm, supersede + cross-tenant staleness."""
    return create_async_engine(
        get_settings().database_url_owner,
        poolclass=NullPool,
        connect_args={"statement_cache_size": 0},
    )


@dataclass(frozen=True)
class JobRow:
    id: int
    kind: str
    status: str
    attempts: int
    error: str | None


async def enqueue_ingest(
    *,
    source_url: str,
    file_path: str | None,
    title: str,
    issuing_body: str,
    document_type: str,
    jurisdiction: str,
    published_date: dt.date,
) -> int:
    payload: dict[str, object] = {
        "source_url": source_url,
        "title": title,
        "issuing_body": issuing_body,
        "document_type": document_type,
        "jurisdiction": jurisdiction,
        "published_date": published_date.isoformat(),
    }
    if file_path:
        payload["file_path"] = file_path
    engine = _worker_engine()
    try:
        async with engine.begin() as conn:
            job_id = (
                await conn.execute(
                    text(
                        "INSERT INTO jobs (kind, status, payload, attempts, max_attempts) "
                        "VALUES (:kind, 'queued', CAST(:payload AS jsonb), 0, 3) RETURNING id"
                    ),
                    {"kind": JobKind.INGEST.value, "payload": _json(payload)},
                )
            ).scalar_one()
            return int(job_id)
    finally:
        await engine.dispose()


def _json(payload: dict[str, object]) -> str:
    return json.dumps(payload)


async def run_worker_once(*, max_jobs: int | None = None) -> int:
    engine = _worker_engine()
    try:
        worker = Worker(engine, get_embedding_provider(), get_chat_provider(), name="cli-worker")
        await worker.reap()
        return await worker.drain(max_jobs=max_jobs)
    finally:
        await engine.dispose()


async def list_jobs(*, status: str | None) -> list[JobRow]:
    engine = _worker_engine()
    try:
        async with engine.connect() as conn:
            stmt = "SELECT id, kind, status, attempts, error FROM jobs"
            params: dict[str, str] = {}
            if status:
                stmt += " WHERE status = :status"
                params["status"] = status
            stmt += " ORDER BY id DESC LIMIT 50"
            rows = (await conn.execute(text(stmt), params)).fetchall()
            return [JobRow(*row) for row in rows]
    finally:
        await engine.dispose()


async def list_review_documents() -> list[tuple[int, str, str | None]]:
    engine = _worker_engine()
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT id, title, review_reason FROM regulatory_documents "
                        "WHERE extraction_status = 'review' ORDER BY id DESC LIMIT 50"
                    )
                )
            ).fetchall()
            return [(row[0], row[1], row[2]) for row in rows]
    finally:
        await engine.dispose()


async def confirm(document_id: int) -> None:
    engine = _owner_engine()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await confirm_document(session, document_id)
    finally:
        await engine.dispose()


async def supersede(
    *, new_document_id: int, old_document_id: int, relation: str
) -> SupersedeReport:
    engine = _owner_engine()  # staleness flagger is a cross-tenant maintenance write
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            return await confirm_supersession(
                session,
                superseded_document_id=old_document_id,
                superseding_document_id=new_document_id,
                relation=relation,
            )
    finally:
        await engine.dispose()


async def backfill_embeddings() -> int:
    engine = _worker_engine()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            return await embed_pending_chunks(session, get_embedding_provider())
    finally:
        await engine.dispose()


async def retry_job(job_id: int) -> bool:
    engine = _worker_engine()
    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "UPDATE jobs SET status = 'queued', error = NULL, attempts = 0 "
                    "WHERE id = :id AND status = 'failed'"
                ),
                {"id": job_id},
            )
            return result.rowcount == 1
    finally:
        await engine.dispose()
