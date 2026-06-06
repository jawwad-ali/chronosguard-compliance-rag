"""Policy CRUD with immutable versioning.

RLS already scopes every query to the request tenant; ``tenant_id`` is still
set explicitly on writes (WITH CHECK requires it) and filters stay explicit
about soft-deletion. Defense in depth, not either/or.
"""

import datetime as dt

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from chronosguard.core.pagination import PageParams
from chronosguard.models import OrgPolicy, OrgPolicyVersion


def _alive() -> ColumnElement[bool]:
    return col(OrgPolicy.deleted_at).is_(None)


async def create_policy(
    session: AsyncSession, *, tenant_id: int, title: str, body: str
) -> tuple[OrgPolicy, OrgPolicyVersion]:
    policy = OrgPolicy(tenant_id=tenant_id, title=title, current_version_no=1)
    session.add(policy)
    await session.flush()
    assert policy.id is not None  # noqa: S101 — identity assigned at flush
    version = OrgPolicyVersion(tenant_id=tenant_id, policy_id=policy.id, version_no=1, body=body)
    session.add(version)
    await session.flush()
    return policy, version


async def get_policy(
    session: AsyncSession, policy_id: int
) -> tuple[OrgPolicy, OrgPolicyVersion] | None:
    policy = (
        await session.execute(select(OrgPolicy).where(col(OrgPolicy.id) == policy_id, _alive()))
    ).scalar_one_or_none()
    if policy is None:
        return None
    version = (
        await session.execute(
            select(OrgPolicyVersion).where(
                col(OrgPolicyVersion.policy_id) == policy_id,
                col(OrgPolicyVersion.version_no) == policy.current_version_no,
            )
        )
    ).scalar_one()
    return policy, version


async def list_policies(session: AsyncSession, page: PageParams) -> tuple[list[OrgPolicy], int]:
    base = select(OrgPolicy).where(_alive())
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        (
            await session.execute(
                base.order_by(col(OrgPolicy.updated_at).desc(), col(OrgPolicy.id).desc())
                .limit(page.limit)
                .offset(page.offset)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), int(total)


async def update_policy(
    session: AsyncSession, policy_id: int, *, title: str | None, body: str | None
) -> tuple[OrgPolicy, OrgPolicyVersion] | None:
    found = await get_policy(session, policy_id)
    if found is None:
        return None
    policy, current = found

    if title is not None:
        policy.title = title
    if body is not None and body != current.body:
        next_no = policy.current_version_no + 1
        current = OrgPolicyVersion(
            tenant_id=policy.tenant_id,
            policy_id=policy_id,
            version_no=next_no,
            body=body,
        )
        session.add(current)
        policy.current_version_no = next_no
    session.add(policy)
    await session.flush()
    return policy, current


async def soft_delete_policy(session: AsyncSession, policy_id: int) -> bool:
    found = await get_policy(session, policy_id)
    if found is None:
        return False
    policy, _ = found
    policy.deleted_at = dt.datetime.now(dt.UTC)
    session.add(policy)
    await session.flush()
    return True


async def list_versions(
    session: AsyncSession, policy_id: int, page: PageParams
) -> tuple[list[OrgPolicyVersion], int] | None:
    if await get_policy(session, policy_id) is None:
        return None
    base = select(OrgPolicyVersion).where(col(OrgPolicyVersion.policy_id) == policy_id)
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        (
            await session.execute(
                base.order_by(col(OrgPolicyVersion.version_no).desc())
                .limit(page.limit)
                .offset(page.offset)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), int(total)
