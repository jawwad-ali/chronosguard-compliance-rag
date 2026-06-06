"""GET /api/v1/me — proves the auth → tenancy → RLS chain end-to-end."""

from typing import Annotated

from fastapi import APIRouter, Depends

from chronosguard.core.errors import NotFoundError
from chronosguard.core.tenancy import SCOPE_READ, Principal, TenantSessionDep, require_scope
from chronosguard.models import Organization
from chronosguard.schemas.org import OrgOut

router = APIRouter(tags=["me"])


@router.get("/me", operation_id="get_my_organization", response_model=OrgOut)
async def get_me(
    principal: Annotated[Principal, Depends(require_scope(SCOPE_READ))],
    session: TenantSessionDep,
) -> OrgOut:
    org = await session.get(Organization, principal.tenant_id)
    if org is None:  # RLS context bug or offboarded tenant — never leak which
        raise NotFoundError("Organization")
    return OrgOut.model_validate(org)
