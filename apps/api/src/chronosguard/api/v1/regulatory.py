"""Regulatory corpus browse (global, read-only; citation tracing for the UI)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from chronosguard.core.errors import NotFoundError
from chronosguard.core.pagination import Page, PageParamsDep
from chronosguard.core.tenancy import SCOPE_READ, Principal, SessionDep, require_scope
from chronosguard.schemas.regulatory import ChunkOut, DocumentDetail, DocumentSummary
from chronosguard.services import corpus

router = APIRouter(prefix="/regulatory", tags=["regulatory"])

ReadPrincipal = Annotated[Principal, Depends(require_scope(SCOPE_READ))]


@router.get(
    "/documents", operation_id="list_regulatory_documents", response_model=Page[DocumentSummary]
)
async def list_documents(
    _principal: ReadPrincipal,
    session: SessionDep,
    page: PageParamsDep,
    jurisdiction: Annotated[str | None, Query(max_length=16)] = None,
    issuing_body: Annotated[str | None, Query(max_length=64)] = None,
    document_type: Annotated[str | None, Query(max_length=32)] = None,
) -> Page[DocumentSummary]:
    docs, total = await corpus.list_documents(
        session,
        jurisdiction=jurisdiction,
        issuing_body=issuing_body,
        document_type=document_type,
        page=page,
    )
    return Page(
        items=[DocumentSummary.model_validate(doc) for doc in docs],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/documents/{document_id}",
    operation_id="get_regulatory_document",
    response_model=DocumentDetail,
)
async def get_document(
    document_id: int, _principal: ReadPrincipal, session: SessionDep
) -> DocumentDetail:
    found = await corpus.get_document(session, document_id)
    if found is None:
        raise NotFoundError("Regulatory document", document_id)
    doc, chunk_count = found
    return DocumentDetail(
        **DocumentSummary.model_validate(doc).model_dump(),
        source_url=doc.source_url,
        ingested_at=doc.ingested_at,
        chunk_count=chunk_count,
    )


@router.get(
    "/documents/{document_id}/chunks",
    operation_id="list_regulatory_document_chunks",
    response_model=Page[ChunkOut],
)
async def list_document_chunks(
    document_id: int, _principal: ReadPrincipal, session: SessionDep, page: PageParamsDep
) -> Page[ChunkOut]:
    found = await corpus.list_chunks(session, document_id, page)
    if found is None:
        raise NotFoundError("Regulatory document", document_id)
    chunks, total = found
    return Page(
        items=[ChunkOut.model_validate(chunk) for chunk in chunks],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )
