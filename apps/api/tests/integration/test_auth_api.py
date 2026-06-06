"""The auth → tenancy → RLS chain, end-to-end over HTTP.

The app's session dependency is overridden to connect as cg_app against the
test container — the same least-privilege role production uses, so these
requests exercise real RLS, not a simulation of it. (Fixtures: tests/conftest.py.)
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import issue_key as _issue_key

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


class TestAuthFailures:
    async def test_missing_key_is_401(self, api: AsyncClient, two_orgs: tuple[int, int]) -> None:
        response = await api.get("/api/v1/me")
        assert response.status_code == 401
        assert response.headers["content-type"].startswith("application/problem+json")

    async def test_malformed_key_is_401(self, api: AsyncClient, two_orgs: tuple[int, int]) -> None:
        response = await api.get("/api/v1/me", headers={"X-API-Key": "not-a-real-key"})
        assert response.status_code == 401

    async def test_wrong_secret_with_valid_prefix_is_401(
        self, api: AsyncClient, owner_engine: AsyncEngine, two_orgs: tuple[int, int]
    ) -> None:
        org_a, _ = two_orgs
        full_key = await _issue_key(owner_engine, org_a, ["read"])
        prefix = full_key.split(".")[0]
        response = await api.get("/api/v1/me", headers={"X-API-Key": f"{prefix}.forged-secret"})
        assert response.status_code == 401

    async def test_revoked_key_is_401(
        self, api: AsyncClient, owner_engine: AsyncEngine, two_orgs: tuple[int, int]
    ) -> None:
        org_a, _ = two_orgs
        full_key = await _issue_key(owner_engine, org_a, ["read"], revoked=True)
        response = await api.get("/api/v1/me", headers={"X-API-Key": full_key})
        assert response.status_code == 401

    async def test_key_without_required_scope_is_403(
        self, api: AsyncClient, owner_engine: AsyncEngine, two_orgs: tuple[int, int]
    ) -> None:
        org_a, _ = two_orgs
        full_key = await _issue_key(owner_engine, org_a, ["bogus_scope"])
        response = await api.get("/api/v1/me", headers={"X-API-Key": full_key})
        assert response.status_code == 403


class TestTenantScopedRequests:
    async def test_me_returns_own_organization(
        self, api: AsyncClient, owner_engine: AsyncEngine, two_orgs: tuple[int, int]
    ) -> None:
        org_a, _ = two_orgs
        full_key = await _issue_key(owner_engine, org_a, ["read"])
        response = await api.get("/api/v1/me", headers={"X-API-Key": full_key})
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == org_a
        assert body["name"] == "PocketPay"

    @pytest.mark.rls
    async def test_two_keys_resolve_to_their_own_tenants(
        self, api: AsyncClient, owner_engine: AsyncEngine, two_orgs: tuple[int, int]
    ) -> None:
        org_a, org_b = two_orgs
        key_a = await _issue_key(owner_engine, org_a, ["read"])
        key_b = await _issue_key(owner_engine, org_b, ["read"])

        seen_a = (await api.get("/api/v1/me", headers={"X-API-Key": key_a})).json()
        seen_b = (await api.get("/api/v1/me", headers={"X-API-Key": key_b})).json()

        assert seen_a["id"] == org_a
        assert seen_b["id"] == org_b
        assert seen_a["id"] != seen_b["id"]

    async def test_successful_auth_stamps_last_used_at(
        self, api: AsyncClient, owner_engine: AsyncEngine, two_orgs: tuple[int, int]
    ) -> None:
        org_a, _ = two_orgs
        full_key = await _issue_key(owner_engine, org_a, ["read"])
        await api.get("/api/v1/me", headers={"X-API-Key": full_key})

        async with owner_engine.connect() as conn:
            stamped = (
                await conn.execute(
                    text("SELECT last_used_at FROM api_keys WHERE prefix = :p"),
                    {"p": full_key.split(".")[0]},
                )
            ).scalar_one()
        assert stamped is not None
