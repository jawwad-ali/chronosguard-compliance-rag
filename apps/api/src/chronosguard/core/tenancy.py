"""The tenancy mechanism, end-to-end (docs/ARCHITECTURE.md §3.5).

``X-API-Key`` → prefix lookup → constant-time verify → ``Principal`` →
``SET LOCAL app.tenant_id`` inside the request transaction → Postgres RLS.

FastAPI caches dependency results per request, so ``get_session`` resolves to
ONE AsyncSession shared by ``authenticate``, ``tenant_session``, and the
handler — guaranteeing SET LOCAL runs on the exact connection/transaction the
handler queries. ``is_local=true`` scopes the GUC to this transaction: a
pooled connection can never carry a previous request's tenant.
"""

import datetime as dt
from collections.abc import Callable, Coroutine
from typing import Annotated

import structlog
from fastapi import Depends, Header
from pydantic import BaseModel
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from chronosguard.core.db import get_session
from chronosguard.core.errors import ForbiddenError, UnauthorizedError
from chronosguard.core.security import extract_prefix, verify_api_key
from chronosguard.models import ApiKey

SCOPE_READ = "read"
SCOPE_AUDIT = "audit"
SCOPE_ADMIN = "admin"

#: Scope hierarchy: admin ⊃ audit ⊃ read.
_IMPLIED: dict[str, frozenset[str]] = {
    SCOPE_READ: frozenset({SCOPE_READ}),
    SCOPE_AUDIT: frozenset({SCOPE_AUDIT, SCOPE_READ}),
    SCOPE_ADMIN: frozenset({SCOPE_ADMIN, SCOPE_AUDIT, SCOPE_READ}),
}

_INVALID_KEY_MESSAGE = "Invalid, revoked, or expired API key"


class Principal(BaseModel):
    tenant_id: int
    api_key_id: int
    scopes: frozenset[str]


def effective_scopes(granted: list[str] | frozenset[str]) -> frozenset[str]:
    expanded: set[str] = set()
    for scope in granted:
        expanded |= _IMPLIED.get(scope, frozenset())
    return frozenset(expanded)


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def authenticate(
    session: SessionDep,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> Principal:
    if not x_api_key:
        raise UnauthorizedError("Missing X-API-Key header")

    prefix = extract_prefix(x_api_key)
    if prefix is None:
        raise UnauthorizedError(_INVALID_KEY_MESSAGE)

    row = (
        await session.execute(select(ApiKey).where(col(ApiKey.prefix) == prefix))
    ).scalar_one_or_none()
    now = dt.datetime.now(dt.UTC)
    if (
        row is None
        or row.id is None
        or not verify_api_key(x_api_key, row.key_hash)
        or row.revoked_at is not None
        or (row.expires_at is not None and row.expires_at <= now)
    ):
        raise UnauthorizedError(_INVALID_KEY_MESSAGE)

    await session.execute(update(ApiKey).where(col(ApiKey.id) == row.id).values(last_used_at=now))
    structlog.contextvars.bind_contextvars(tenant_id=row.tenant_id)
    return Principal(
        tenant_id=row.tenant_id, api_key_id=row.id, scopes=effective_scopes(row.scopes)
    )


PrincipalDep = Annotated[Principal, Depends(authenticate)]


async def tenant_session(principal: PrincipalDep, session: SessionDep) -> AsyncSession:
    """The request session with RLS tenant context set (transaction-local)."""
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(principal.tenant_id)},
    )
    return session


TenantSessionDep = Annotated[AsyncSession, Depends(tenant_session)]


def require_scope(scope: str) -> Callable[..., Coroutine[None, None, Principal]]:
    async def _guard(principal: PrincipalDep) -> Principal:
        if scope not in principal.scopes:
            raise ForbiddenError(f"Requires scope: {scope}")
        return principal

    return _guard
