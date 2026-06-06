"""Tenant policy CRUD — every route runs under tenant_session (RLS context)."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from chronosguard.core.errors import NotFoundError
from chronosguard.core.pagination import Page, PageParamsDep
from chronosguard.core.tenancy import (
    SCOPE_AUDIT,
    SCOPE_READ,
    Principal,
    TenantSessionDep,
    require_scope,
)
from chronosguard.schemas.policy import (
    PolicyCreate,
    PolicyOut,
    PolicySummary,
    PolicyUpdate,
    PolicyVersionOut,
)
from chronosguard.services import policies

router = APIRouter(prefix="/policies", tags=["policies"])

ReadPrincipal = Annotated[Principal, Depends(require_scope(SCOPE_READ))]
AuditPrincipal = Annotated[Principal, Depends(require_scope(SCOPE_AUDIT))]


def _to_out(policy: object, version: object) -> PolicyOut:
    summary = PolicySummary.model_validate(policy)
    body: str = version.body  # type: ignore[attr-defined]
    return PolicyOut(**summary.model_dump(), body=body)


@router.post(
    "",
    operation_id="create_policy",
    response_model=PolicyOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_policy(
    body: PolicyCreate, principal: AuditPrincipal, session: TenantSessionDep
) -> PolicyOut:
    policy, version = await policies.create_policy(
        session, tenant_id=principal.tenant_id, title=body.title, body=body.body
    )
    return _to_out(policy, version)


@router.get("", operation_id="list_policies", response_model=Page[PolicySummary])
async def list_policies(
    _principal: ReadPrincipal, session: TenantSessionDep, page: PageParamsDep
) -> Page[PolicySummary]:
    rows, total = await policies.list_policies(session, page)
    return Page(
        items=[PolicySummary.model_validate(row) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{policy_id}", operation_id="get_policy", response_model=PolicyOut)
async def get_policy(
    policy_id: int, _principal: ReadPrincipal, session: TenantSessionDep
) -> PolicyOut:
    found = await policies.get_policy(session, policy_id)
    if found is None:
        raise NotFoundError("Policy", policy_id)
    return _to_out(*found)


@router.get(
    "/{policy_id}/versions",
    operation_id="list_policy_versions",
    response_model=Page[PolicyVersionOut],
)
async def list_policy_versions(
    policy_id: int, _principal: ReadPrincipal, session: TenantSessionDep, page: PageParamsDep
) -> Page[PolicyVersionOut]:
    found = await policies.list_versions(session, policy_id, page)
    if found is None:
        raise NotFoundError("Policy", policy_id)
    rows, total = found
    return Page(
        items=[PolicyVersionOut.model_validate(row) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.patch("/{policy_id}", operation_id="update_policy", response_model=PolicyOut)
async def update_policy(
    policy_id: int, body: PolicyUpdate, _principal: AuditPrincipal, session: TenantSessionDep
) -> PolicyOut:
    found = await policies.update_policy(session, policy_id, title=body.title, body=body.body)
    if found is None:
        raise NotFoundError("Policy", policy_id)
    return _to_out(*found)


@router.delete("/{policy_id}", operation_id="delete_policy", status_code=status.HTTP_204_NO_CONTENT)
async def delete_policy(
    policy_id: int, _principal: AuditPrincipal, session: TenantSessionDep
) -> None:
    if not await policies.soft_delete_policy(session, policy_id):
        raise NotFoundError("Policy", policy_id)
