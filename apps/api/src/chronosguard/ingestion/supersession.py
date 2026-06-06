"""Operator-confirmed supersession + the staleness flagger.

One atomic operation (docs/ARCHITECTURE.md §3.3): close the old chunks'
validity intervals (THE retrieval mechanism), record lineage edges (diff-UI
metadata), and flag past audit runs whose stored verdicts a retroactive
amendment may have invalidated. Auto-linking is deliberately absent: a wrong
link silently removes in-force law from audits.
"""

import datetime as dt
from dataclasses import dataclass

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from chronosguard.core.errors import NotFoundError, UnprocessableError
from chronosguard.models import (
    ExtractionStatus,
    RegulatoryChunk,
    RegulatoryDocument,
    Supersession,
)

logger = structlog.get_logger(__name__)

_STALENESS_SQL = text(
    """
    UPDATE audit_runs
    SET stale = true
    WHERE as_of_date >= :effective_date
      AND stale = false
      AND EXISTS (
          SELECT 1 FROM jsonb_array_elements(retrieved_chunk_ids) AS element
          WHERE element::text::bigint = ANY(:chunk_ids)
      )
    RETURNING id
    """
)


@dataclass(frozen=True)
class SupersedeReport:
    superseded_chunks: int
    edges_created: int
    stale_runs_flagged: int
    supersession_effective_date: dt.date


async def confirm_document(session: AsyncSession, document_id: int) -> None:
    """Operator clears a review-quarantined document into retrieval."""
    document = await session.get(RegulatoryDocument, document_id)
    if document is None:
        raise NotFoundError("Regulatory document", document_id)
    document.extraction_status = ExtractionStatus.CONFIRMED.value
    document.review_reason = None
    session.add(document)
    await session.commit()
    logger.info("document_confirmed", document_id=document_id)


async def confirm_supersession(
    session: AsyncSession,
    *,
    superseded_document_id: int,
    superseding_document_id: int,
    relation: str,
) -> SupersedeReport:
    new_effective = (
        await session.execute(
            select(func.min(RegulatoryChunk.effective_date)).where(
                col(RegulatoryChunk.document_id) == superseding_document_id
            )
        )
    ).scalar_one_or_none()
    if new_effective is None:
        raise NotFoundError("Superseding document chunks", superseding_document_id)

    old_chunks = list(
        (
            await session.execute(
                select(RegulatoryChunk).where(
                    col(RegulatoryChunk.document_id) == superseded_document_id,
                    col(RegulatoryChunk.expiration_date).is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    if not old_chunks:
        raise NotFoundError("Open-ended chunks to supersede", superseded_document_id)
    if any(chunk.effective_date >= new_effective for chunk in old_chunks):
        msg = (
            "Superseding effective date must postdate every superseded chunk "
            "(a same-day replacement is a correction, not a supersession)"
        )
        raise UnprocessableError(msg)

    new_chunk_id = (
        await session.execute(
            select(col(RegulatoryChunk.id))
            .where(col(RegulatoryChunk.document_id) == superseding_document_id)
            .order_by(col(RegulatoryChunk.chunk_index))
            .limit(1)
        )
    ).scalar_one()

    old_ids: list[int] = []
    for chunk in old_chunks:
        chunk.expiration_date = new_effective  # THE retrieval mechanism
        session.add(chunk)
        assert chunk.id is not None  # noqa: S101
        old_ids.append(chunk.id)
        session.add(
            Supersession(  # lineage metadata, never in the hot path
                superseded_chunk_id=chunk.id,
                superseding_chunk_id=new_chunk_id,
                relation=relation,
                supersession_effective_date=new_effective,
            )
        )

    # Staleness: stored verdicts anchored on/after the (possibly retroactive)
    # effective date that reasoned over now-expired chunks must not rot silently.
    stale_rows = (
        await session.execute(
            _STALENESS_SQL, {"effective_date": new_effective, "chunk_ids": old_ids}
        )
    ).fetchall()
    await session.commit()

    report = SupersedeReport(
        superseded_chunks=len(old_ids),
        edges_created=len(old_ids),
        stale_runs_flagged=len(stale_rows),
        supersession_effective_date=new_effective,
    )
    logger.info(
        "supersession_confirmed",
        superseded_document_id=superseded_document_id,
        superseding_document_id=superseding_document_id,
        relation=relation,
        **report.__dict__,
    )
    return report
