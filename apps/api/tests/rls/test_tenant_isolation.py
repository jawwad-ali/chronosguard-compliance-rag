"""Cross-tenant isolation proofs — the blocking security lane.

Every test connects as a runtime role (cg_app / cg_worker), never as the
owner: a superuser silently bypasses RLS, so an owner-connected "pass" proves
nothing. A red test in this file is a security incident, not a flaky test.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.db import set_tenant_context

pytestmark = [pytest.mark.rls, pytest.mark.anyio]


class TestSelectIsolation:
    async def test_sees_only_own_organization(
        self, app_engine: AsyncEngine, two_orgs: tuple[int, int]
    ) -> None:
        org_a, _org_b = two_orgs
        async with app_engine.connect() as conn:
            await set_tenant_context(conn, org_a)
            rows = (await conn.execute(text("SELECT id FROM organizations"))).fetchall()
        assert [row[0] for row in rows] == [org_a]

    async def test_other_tenant_is_invisible_not_forbidden(
        self, app_engine: AsyncEngine, two_orgs: tuple[int, int]
    ) -> None:
        org_a, org_b = two_orgs
        async with app_engine.connect() as conn:
            await set_tenant_context(conn, org_a)
            result = await conn.execute(
                text("SELECT count(*) FROM organizations WHERE id = :other"), {"other": org_b}
            )
        assert result.scalar_one() == 0  # invisible — no existence leak

    async def test_no_context_returns_zero_rows(
        self, app_engine: AsyncEngine, two_orgs: tuple[int, int]
    ) -> None:
        """Fail-closed: a forgotten SET LOCAL can never leak data."""
        async with app_engine.connect() as conn:
            result = await conn.execute(text("SELECT count(*) FROM organizations"))
        assert result.scalar_one() == 0

    async def test_empty_string_context_fails_closed_not_500(
        self, app_engine: AsyncEngine, two_orgs: tuple[int, int]
    ) -> None:
        """NULLIF guard: empty string casts to NULL, not an invalid-syntax error."""
        async with app_engine.connect() as conn:
            await set_tenant_context(conn, None)  # sets ''
            result = await conn.execute(text("SELECT count(*) FROM organizations"))
        assert result.scalar_one() == 0

    async def test_context_is_transaction_local(
        self, app_engine: AsyncEngine, two_orgs: tuple[int, int]
    ) -> None:
        """A pooled connection must not inherit the previous transaction's tenant."""
        org_a, _ = two_orgs
        async with app_engine.connect() as conn:
            await set_tenant_context(conn, org_a)
            await conn.commit()  # transaction ends; SET LOCAL must die with it
            result = await conn.execute(text("SELECT count(*) FROM organizations"))
        assert result.scalar_one() == 0


class TestWriteIsolation:
    async def test_update_of_other_tenant_is_a_noop(
        self, app_engine: AsyncEngine, two_orgs: tuple[int, int]
    ) -> None:
        org_a, org_b = two_orgs
        async with app_engine.connect() as conn:
            await set_tenant_context(conn, org_a)
            result = await conn.execute(
                text("UPDATE api_keys SET last_used_at = now() WHERE tenant_id = :other"),
                {"other": org_b},
            )
        assert result.rowcount == 0

    async def test_app_role_cannot_insert_organizations(
        self, app_engine: AsyncEngine, two_orgs: tuple[int, int]
    ) -> None:
        """Provisioning is an owner operation; cg_app has no INSERT grant."""
        async with app_engine.connect() as conn:
            await set_tenant_context(conn, two_orgs[0])
            with pytest.raises(ProgrammingError, match="permission denied"):
                await conn.execute(
                    text(
                        "INSERT INTO organizations (name, home_jurisdiction) "
                        "VALUES ('Mallory Inc', 'PK')"
                    )
                )


class TestBootstrapTables:
    async def test_api_keys_readable_without_tenant_context(
        self, app_engine: AsyncEngine, two_orgs: tuple[int, int]
    ) -> None:
        """Auth bootstrap: key lookup must work before any context exists."""
        async with app_engine.connect() as conn:
            result = await conn.execute(text("SELECT count(*) FROM api_keys"))
        assert result.scalar_one() == 0  # readable (no permission error), just empty

    async def test_app_role_can_enqueue_jobs(
        self, app_engine: AsyncEngine, owner_engine: AsyncEngine, two_orgs: tuple[int, int]
    ) -> None:
        org_a, _ = two_orgs
        async with app_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO jobs (kind, status, tenant_id, attempts, max_attempts) "
                    "VALUES ('audit', 'queued', :tid, 0, 3)"
                ),
                {"tid": org_a},
            )
        async with owner_engine.begin() as conn:
            count = (await conn.execute(text("SELECT count(*) FROM jobs"))).scalar_one()
            await conn.execute(text("DELETE FROM jobs"))
        assert count == 1


class TestWorkerRole:
    async def test_worker_bound_by_same_tenant_policy(
        self, worker_engine: AsyncEngine, two_orgs: tuple[int, int]
    ) -> None:
        _org_a, org_b = two_orgs
        async with worker_engine.connect() as conn:
            await set_tenant_context(conn, org_b)
            rows = (await conn.execute(text("SELECT id FROM organizations"))).fetchall()
        assert [row[0] for row in rows] == [org_b]

    async def test_worker_sees_queue_without_tenant_context(
        self, worker_engine: AsyncEngine, two_orgs: tuple[int, int]
    ) -> None:
        """The global queue is visible across tenants — that's how claiming works."""
        async with worker_engine.connect() as conn:
            result = await conn.execute(text("SELECT count(*) FROM jobs"))
        assert result.scalar_one() == 0  # no permission error
