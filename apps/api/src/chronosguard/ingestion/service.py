"""Ingestion orchestrator: bytes/markdown → quarantine checks → chunks → embeddings.

Commits in stages (document+chunks, then per embedding batch) so a crash
mid-embedding loses nothing: ``backfill_embeddings`` resumes exactly where
``embedded_at IS NULL``. Corrected re-publishes (same URL, new content) create
a NEW version row; prior versions are quarantined to review — past audit
findings stay resolvable, the corrected text takes over retrieval.
"""

import datetime as dt
import hashlib
from dataclasses import dataclass

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from chronosguard.ingestion.chunker import chunk_document
from chronosguard.ingestion.extract import (
    extract_markdown,
    has_injection_patterns,
    is_non_english_primary,
    is_scanned,
)
from chronosguard.ingestion.metadata import extract_metadata
from chronosguard.models import (
    ExtractionStatus,
    RegulatoryChunk,
    RegulatoryDocument,
)
from chronosguard.providers.base import EmbeddingProvider

logger = structlog.get_logger(__name__)

EMBED_PERSIST_BATCH = 64


@dataclass(frozen=True)
class IngestHints:
    source_url: str
    title: str
    issuing_body: str
    document_type: str
    jurisdiction: str
    published_date: dt.date
    source_etag: str | None = None


@dataclass(frozen=True)
class IngestOutcome:
    document_id: int
    status: str
    review_reason: str | None
    chunk_count: int
    deduped: bool
    supersedes_refs: list[str]


def _hash(data: bytes | str) -> str:
    raw = data.encode() if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()


async def _existing_by_hash(
    session: AsyncSession, source_url: str, content_hash: str
) -> int | None:
    return (
        await session.execute(
            select(col(RegulatoryDocument.id)).where(
                col(RegulatoryDocument.source_url) == source_url,
                col(RegulatoryDocument.content_hash) == content_hash,
            )
        )
    ).scalar_one_or_none()


async def _next_version_quarantining_priors(session: AsyncSession, source_url: str) -> int:
    """Same URL, new content = corrected re-publish: prior versions leave
    retrieval (review quarantine) but their rows/chunks survive for evidence."""
    max_version = (
        await session.execute(
            select(func.max(RegulatoryDocument.version)).where(
                col(RegulatoryDocument.source_url) == source_url
            )
        )
    ).scalar_one_or_none()
    if max_version is None:
        return 1
    await session.execute(
        update(RegulatoryDocument)
        .where(col(RegulatoryDocument.source_url) == source_url)
        .values(
            extraction_status=ExtractionStatus.REVIEW.value,
            review_reason="superseded_by_correction",
        )
    )
    return int(max_version) + 1


def _quarantine_reason(markdown: str, *, used_fallback: bool) -> str | None:
    if is_non_english_primary(markdown):
        return "non_english"
    if has_injection_patterns(markdown):
        return "injection_flag"
    if used_fallback:
        return "no_structure"
    return None


async def ingest_markdown(
    session: AsyncSession,
    embedder: EmbeddingProvider,
    *,
    markdown: str,
    hints: IngestHints,
) -> IngestOutcome:
    content_hash = _hash(markdown)
    existing = await _existing_by_hash(session, hints.source_url, content_hash)
    if existing is not None:
        return IngestOutcome(
            document_id=existing,
            status="unchanged",
            review_reason=None,
            chunk_count=0,
            deduped=True,
            supersedes_refs=[],
        )

    version = await _next_version_quarantining_priors(session, hints.source_url)
    metadata = extract_metadata(markdown, published_date=hints.published_date)
    chunking = chunk_document(markdown, doc_title=hints.title)
    reason = _quarantine_reason(markdown, used_fallback=chunking.used_fallback)
    status = ExtractionStatus.REVIEW.value if reason else ExtractionStatus.CONFIRMED.value

    document = RegulatoryDocument(
        title=hints.title,
        issuing_body=hints.issuing_body,
        document_type=hints.document_type,
        jurisdiction=hints.jurisdiction,
        source_url=hints.source_url,
        source_etag=hints.source_etag,
        content_hash=content_hash,
        version=version,
        published_date=hints.published_date,
        extraction_status=status,
        review_reason=reason,
        raw_markdown=markdown,
    )
    session.add(document)
    await session.flush()
    assert document.id is not None  # noqa: S101

    for draft in chunking.chunks:
        session.add(
            RegulatoryChunk(
                document_id=document.id,
                chunk_index=draft.index,
                content=draft.text,
                embed_text_hash=_hash(draft.embed_text),
                legal_citation=draft.legal_citation,
                heading_path=draft.heading_path,
                jurisdiction=hints.jurisdiction,
                effective_date=metadata.effective_date,
                effective_date_source=metadata.effective_date_source,
                token_count=max(1, len(draft.text) // 4),
                embedding_model=embedder.model,
            )
        )
    await session.commit()  # stage 1 durable: doc + unembedded chunks

    embedded = await embed_pending_chunks(session, embedder, document_id=document.id)
    logger.info(
        "document_ingested",
        document_id=document.id,
        status=status,
        review_reason=reason,
        version=version,
        chunks=len(chunking.chunks),
        embedded=embedded,
        effective_date=str(metadata.effective_date),
        effective_date_source=metadata.effective_date_source,
        supersedes_refs=metadata.supersedes_refs,  # operator suggestion, never auto-linked
    )
    return IngestOutcome(
        document_id=document.id,
        status=status,
        review_reason=reason,
        chunk_count=len(chunking.chunks),
        deduped=False,
        supersedes_refs=metadata.supersedes_refs,
    )


async def ingest_bytes(
    session: AsyncSession,
    embedder: EmbeddingProvider,
    *,
    content: bytes,
    hints: IngestHints,
) -> IngestOutcome:
    extracted = await extract_markdown(content)
    if is_scanned(extracted):
        document = RegulatoryDocument(
            title=hints.title,
            issuing_body=hints.issuing_body,
            document_type=hints.document_type,
            jurisdiction=hints.jurisdiction,
            source_url=hints.source_url,
            source_etag=hints.source_etag,
            content_hash=_hash(content),
            version=await _next_version_quarantining_priors(session, hints.source_url),
            published_date=hints.published_date,
            extraction_status=ExtractionStatus.REVIEW.value,
            review_reason="scanned_pdf",
        )
        session.add(document)
        await session.commit()
        assert document.id is not None  # noqa: S101
        return IngestOutcome(
            document_id=document.id,
            status=ExtractionStatus.REVIEW.value,
            review_reason="scanned_pdf",
            chunk_count=0,
            deduped=False,
            supersedes_refs=[],
        )
    return await ingest_markdown(session, embedder, markdown=extracted.markdown, hints=hints)


async def embed_pending_chunks(
    session: AsyncSession,
    embedder: EmbeddingProvider,
    *,
    document_id: int | None = None,
    batch_size: int = EMBED_PERSIST_BATCH,
) -> int:
    """Embed every chunk with ``embedded_at IS NULL``; commit per batch."""
    total = 0
    while True:
        stmt = (
            select(RegulatoryChunk)
            .where(col(RegulatoryChunk.embedded_at).is_(None))
            .order_by(col(RegulatoryChunk.id))
            .limit(batch_size)
        )
        if document_id is not None:
            stmt = stmt.where(col(RegulatoryChunk.document_id) == document_id)
        chunks = list((await session.execute(stmt)).scalars().all())
        if not chunks:
            return total
        vectors = await embedder.embed(
            [f"[{chunk.heading_path}] {chunk.content}" for chunk in chunks]
        )
        now = dt.datetime.now(dt.UTC)
        for chunk, vector in zip(chunks, vectors, strict=True):
            chunk.embedding = vector
            chunk.embedded_at = now
            chunk.embedding_model = embedder.model
            session.add(chunk)
        await session.commit()  # per-batch durability: crash loses at most one batch
        total += len(chunks)
