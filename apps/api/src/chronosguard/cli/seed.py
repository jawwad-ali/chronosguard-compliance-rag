"""Seed loader — idempotent corpus + tenant fixtures (owner-role operation)."""

import datetime as dt
import hashlib

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import col, select

from chronosguard.cli.seed_data import (
    SEED_DOCUMENTS,
    SEED_JURISDICTION,
    SEED_ORGS,
    SEED_SUPERSESSIONS,
    SeedDocument,
    content_hash_for,
    embed_text_for,
)
from chronosguard.core.config import get_settings
from chronosguard.models import (
    RegulatoryChunk,
    RegulatoryDocument,
    Supersession,
)
from chronosguard.providers import EmbeddingProvider, FakeEmbeddings

logger = structlog.get_logger(__name__)


async def _insert_document(
    session: AsyncSession, seed: SeedDocument, embedder: EmbeddingProvider
) -> int:
    doc = RegulatoryDocument(
        title=seed.title,
        issuing_body=seed.issuing_body,
        document_type=seed.document_type,
        jurisdiction=SEED_JURISDICTION[0],
        source_url=seed.source_url,
        content_hash=content_hash_for(seed),
        published_date=seed.published_date,
        extraction_status=seed.extraction_status,
        review_reason=seed.review_reason,
    )
    session.add(doc)
    await session.flush()
    assert doc.id is not None  # noqa: S101 — flush assigns identity

    embed_texts = [embed_text_for(chunk) for chunk in seed.chunks]
    vectors = await embedder.embed(embed_texts)
    now = dt.datetime.now(dt.UTC)
    for index, (chunk, vector, embed_text) in enumerate(
        zip(seed.chunks, vectors, embed_texts, strict=True)
    ):
        session.add(
            RegulatoryChunk(
                document_id=doc.id,
                chunk_index=index,
                content=chunk.content,
                embed_text_hash=hashlib.sha256(embed_text.encode()).hexdigest(),
                legal_citation=chunk.legal_citation,
                heading_path=chunk.heading_path,
                jurisdiction=SEED_JURISDICTION[0],
                effective_date=chunk.effective_date,
                effective_date_source=chunk.effective_date_source,
                expiration_date=chunk.expiration_date,
                token_count=max(1, len(chunk.content) // 4),
                embedding_model=embedder.model,
                embedded_at=now,
                embedding=vector,
            )
        )
    return doc.id


async def _ensure_supersessions(session: AsyncSession, doc_ids: dict[str, int]) -> None:
    for edge in SEED_SUPERSESSIONS:
        old_doc_id = doc_ids.get(edge.superseded_doc_key)
        new_doc_id = doc_ids.get(edge.superseding_doc_key)
        if old_doc_id is None or new_doc_id is None:
            continue
        old_chunk = (
            (
                await session.execute(
                    select(RegulatoryChunk).where(col(RegulatoryChunk.document_id) == old_doc_id)
                )
            )
            .scalars()
            .first()
        )
        new_chunk = (
            (
                await session.execute(
                    select(RegulatoryChunk).where(col(RegulatoryChunk.document_id) == new_doc_id)
                )
            )
            .scalars()
            .first()
        )
        if old_chunk is None or new_chunk is None:
            continue
        existing = (
            (
                await session.execute(
                    select(Supersession).where(
                        col(Supersession.superseded_chunk_id) == old_chunk.id
                    )
                )
            )
            .scalars()
            .first()
        )
        if existing is None and old_chunk.id is not None:
            session.add(
                Supersession(
                    superseded_chunk_id=old_chunk.id,
                    superseding_chunk_id=new_chunk.id,
                    relation=edge.relation,
                    supersession_effective_date=edge.effective_date,
                )
            )


async def seed_corpus(engine: AsyncEngine, embedder: EmbeddingProvider | None = None) -> int:
    """Load the seed corpus. Returns how many documents were newly inserted."""
    embedder = embedder or FakeEmbeddings()
    inserted = 0
    async with AsyncSession(engine, expire_on_commit=False) as session:
        code, name = SEED_JURISDICTION
        await session.execute(
            text(
                "INSERT INTO jurisdictions (code, name) VALUES (:code, :name) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "name": name},
        )

        doc_ids: dict[str, int] = {}
        for seed in SEED_DOCUMENTS:
            existing_id = (
                await session.execute(
                    select(RegulatoryDocument.id).where(
                        col(RegulatoryDocument.source_url) == seed.source_url
                    )
                )
            ).scalar_one_or_none()
            if existing_id is not None:
                doc_ids[seed.key] = existing_id
                continue
            doc_ids[seed.key] = await _insert_document(session, seed, embedder)
            inserted += 1

        await _ensure_supersessions(session, doc_ids)

        for org_name, jurisdiction in SEED_ORGS:
            await session.execute(
                text(
                    "INSERT INTO organizations (name, home_jurisdiction) "
                    "VALUES (:name, :jur) ON CONFLICT (name) DO NOTHING"
                ),
                {"name": org_name, "jur": jurisdiction},
            )

        await session.commit()
    logger.info("seed_complete", documents_inserted=inserted)
    return inserted


async def seed_with_default_engine() -> int:
    engine = create_async_engine(
        get_settings().database_url_owner,
        poolclass=NullPool,
        connect_args={"statement_cache_size": 0},
    )
    try:
        return await seed_corpus(engine)
    finally:
        await engine.dispose()
