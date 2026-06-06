"""Regulatory corpus reads. Tenants only ever see CONFIRMED documents —
the review queue is an operator concern."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col
from sqlmodel.sql.expression import SelectOfScalar

from chronosguard.core.pagination import PageParams
from chronosguard.models import ExtractionStatus, RegulatoryChunk, RegulatoryDocument

_CONFIRMED = ExtractionStatus.CONFIRMED.value


def _confirmed_documents() -> SelectOfScalar[RegulatoryDocument]:
    return select(RegulatoryDocument).where(  # type: ignore[return-value]
        col(RegulatoryDocument.extraction_status) == _CONFIRMED
    )


async def list_documents(
    session: AsyncSession,
    *,
    jurisdiction: str | None,
    issuing_body: str | None,
    document_type: str | None,
    page: PageParams,
) -> tuple[list[RegulatoryDocument], int]:
    stmt = _confirmed_documents()
    if jurisdiction:
        stmt = stmt.where(col(RegulatoryDocument.jurisdiction) == jurisdiction)
    if issuing_body:
        stmt = stmt.where(col(RegulatoryDocument.issuing_body) == issuing_body)
    if document_type:
        stmt = stmt.where(col(RegulatoryDocument.document_type) == document_type)

    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (
            await session.execute(
                stmt.order_by(
                    col(RegulatoryDocument.published_date).desc(),
                    col(RegulatoryDocument.id).desc(),
                )
                .limit(page.limit)
                .offset(page.offset)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), int(total)


async def get_document(
    session: AsyncSession, document_id: int
) -> tuple[RegulatoryDocument, int] | None:
    doc = (
        await session.execute(
            _confirmed_documents().where(col(RegulatoryDocument.id) == document_id)
        )
    ).scalar_one_or_none()
    if doc is None:
        return None
    chunk_count = (
        await session.execute(
            select(func.count())
            .select_from(RegulatoryChunk)
            .where(col(RegulatoryChunk.document_id) == document_id)
        )
    ).scalar_one()
    return doc, int(chunk_count)


async def list_chunks(
    session: AsyncSession, document_id: int, page: PageParams
) -> tuple[list[RegulatoryChunk], int] | None:
    if await get_document(session, document_id) is None:
        return None  # unconfirmed or absent — identical 404, no existence leak

    base = select(RegulatoryChunk).where(col(RegulatoryChunk.document_id) == document_id)
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        (
            await session.execute(
                base.order_by(col(RegulatoryChunk.chunk_index))
                .limit(page.limit)
                .offset(page.offset)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), int(total)
