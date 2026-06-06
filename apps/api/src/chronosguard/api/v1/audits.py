"""Audit endpoints — the core loop: POST 202 → poll → findings."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, select
from sqlmodel import col

from chronosguard.audit.service import create_audit_run
from chronosguard.core.errors import NotFoundError
from chronosguard.core.pagination import Page, PageParamsDep
from chronosguard.core.tenancy import (
    SCOPE_AUDIT,
    SCOPE_READ,
    Principal,
    TenantSessionDep,
    require_scope,
)
from chronosguard.models import AuditFinding, AuditRun
from chronosguard.schemas.audit import AuditCreate, AuditRunOut, FindingOut

router = APIRouter(prefix="/audits", tags=["audits"])

ReadPrincipal = Annotated[Principal, Depends(require_scope(SCOPE_READ))]
AuditPrincipal = Annotated[Principal, Depends(require_scope(SCOPE_AUDIT))]


@router.post(
    "",
    operation_id="create_audit",
    response_model=AuditRunOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_audit(
    body: AuditCreate,
    principal: AuditPrincipal,
    session: TenantSessionDep,
    response: Response,
) -> AuditRunOut:
    run = await create_audit_run(session, tenant_id=principal.tenant_id, body=body)
    response.headers["Location"] = f"/api/v1/audits/{run.id}"
    return AuditRunOut.model_validate(run)


@router.get("/{run_id}", operation_id="get_audit", response_model=AuditRunOut)
async def get_audit(
    run_id: int, _principal: ReadPrincipal, session: TenantSessionDep
) -> AuditRunOut:
    run = await session.get(AuditRun, run_id)
    if run is None:
        raise NotFoundError("Audit run", run_id)
    return AuditRunOut.model_validate(run)


@router.get("", operation_id="list_audits", response_model=Page[AuditRunOut])
async def list_audits(
    _principal: ReadPrincipal, session: TenantSessionDep, page: PageParamsDep
) -> Page[AuditRunOut]:
    base = select(AuditRun)
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        (
            await session.execute(
                base.order_by(col(AuditRun.created_at).desc(), col(AuditRun.id).desc())
                .limit(page.limit)
                .offset(page.offset)
            )
        )
        .scalars()
        .all()
    )
    return Page(
        items=[AuditRunOut.model_validate(row) for row in rows],
        total=int(total),
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/{run_id}/findings",
    operation_id="list_audit_findings",
    response_model=Page[FindingOut],
)
async def list_audit_findings(
    run_id: int, _principal: ReadPrincipal, session: TenantSessionDep, page: PageParamsDep
) -> Page[FindingOut]:
    run = await session.get(AuditRun, run_id)
    if run is None:
        raise NotFoundError("Audit run", run_id)
    base = select(AuditFinding).where(col(AuditFinding.run_id) == run_id)
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        (
            await session.execute(
                base.order_by(col(AuditFinding.clause_index), col(AuditFinding.id))
                .limit(page.limit)
                .offset(page.offset)
            )
        )
        .scalars()
        .all()
    )
    return Page(
        items=[FindingOut.model_validate(row) for row in rows],
        total=int(total),
        limit=page.limit,
        offset=page.offset,
    )
