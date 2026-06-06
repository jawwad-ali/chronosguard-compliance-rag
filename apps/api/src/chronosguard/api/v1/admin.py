"""Admin ingestion endpoints — the n8n contract (admin-scoped API key).

n8n monitors regulator index pages and POSTs discovered links; the backend
owns everything else (fetch, parse, dedup, embed, review-gate). Fire 202,
poll the job.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlmodel import col

from chronosguard.core.errors import NotFoundError, UnprocessableError
from chronosguard.core.tenancy import SCOPE_ADMIN, Principal, SessionDep, require_scope
from chronosguard.models import Job, JobKind, Jurisdiction
from chronosguard.schemas.ingest import IngestJobOut, IngestRequest

router = APIRouter(prefix="/admin", tags=["admin"])

AdminPrincipal = Annotated[Principal, Depends(require_scope(SCOPE_ADMIN))]


@router.post(
    "/ingest",
    operation_id="trigger_ingest",
    response_model=IngestJobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_ingest(
    body: IngestRequest, _principal: AdminPrincipal, session: SessionDep, response: Response
) -> IngestJobOut:
    jurisdiction = (
        await session.execute(
            select(Jurisdiction).where(col(Jurisdiction.code) == body.jurisdiction)
        )
    ).scalar_one_or_none()
    if jurisdiction is None:
        raise UnprocessableError(f"Unknown jurisdiction: {body.jurisdiction}")

    job = Job(
        kind=JobKind.INGEST.value,
        payload={
            "source_url": str(body.source_url),
            "title": body.title,
            "issuing_body": body.issuing_body,
            "document_type": body.document_type,
            "jurisdiction": body.jurisdiction,
            "published_date": body.published_date.isoformat(),
            "source_etag": body.source_etag,
        },
    )
    session.add(job)
    await session.flush()
    response.headers["Location"] = f"/api/v1/admin/ingest/{job.id}"
    return IngestJobOut.model_validate(job)


@router.get("/ingest/{job_id}", operation_id="get_ingest_job", response_model=IngestJobOut)
async def get_ingest_job(
    job_id: int, _principal: AdminPrincipal, session: SessionDep
) -> IngestJobOut:
    job = await session.get(Job, job_id)
    if job is None or job.kind != JobKind.INGEST.value:
        raise NotFoundError("Ingest job", job_id)
    return IngestJobOut.model_validate(job)
