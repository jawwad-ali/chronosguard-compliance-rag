"""Policy CRUD: versioning semantics, scope enforcement, cross-tenant isolation."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import issue_key

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

POLICY_BODY_V1 = (
    "PocketPay will hold user funds for up to 7 business days before clearing.\n\n"
    "Customer KYC records are retained for 5 years after account closure."
)
POLICY_BODY_V2 = POLICY_BODY_V1.replace("7 business days", "3 business days")


@pytest.fixture
async def audit_key(owner_engine: AsyncEngine, two_orgs: tuple[int, int]) -> str:
    return await issue_key(owner_engine, two_orgs[0], ["audit"])


async def _create(api: AsyncClient, key: str, title: str = "Funds Policy") -> dict:  # type: ignore[type-arg]
    response = await api.post(
        "/api/v1/policies",
        json={"title": title, "body": POLICY_BODY_V1},
        headers={"X-API-Key": key},
    )
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


class TestCrudAndVersioning:
    async def test_create_starts_at_version_one(self, api: AsyncClient, audit_key: str) -> None:
        created = await _create(api, audit_key)
        assert created["current_version_no"] == 1
        assert created["body"] == POLICY_BODY_V1

    async def test_body_change_appends_immutable_version(
        self, api: AsyncClient, audit_key: str
    ) -> None:
        policy_id = (await _create(api, audit_key))["id"]

        patched = await api.patch(
            f"/api/v1/policies/{policy_id}",
            json={"body": POLICY_BODY_V2},
            headers={"X-API-Key": audit_key},
        )
        assert patched.json()["current_version_no"] == 2

        versions = (
            await api.get(
                f"/api/v1/policies/{policy_id}/versions", headers={"X-API-Key": audit_key}
            )
        ).json()
        assert versions["total"] == 2
        by_no = {v["version_no"]: v["body"] for v in versions["items"]}
        assert by_no[1] == POLICY_BODY_V1  # v1 untouched — immutability
        assert by_no[2] == POLICY_BODY_V2

    async def test_title_only_change_does_not_version(
        self, api: AsyncClient, audit_key: str
    ) -> None:
        policy_id = (await _create(api, audit_key))["id"]
        patched = await api.patch(
            f"/api/v1/policies/{policy_id}",
            json={"title": "Renamed Policy"},
            headers={"X-API-Key": audit_key},
        )
        body = patched.json()
        assert body["title"] == "Renamed Policy"
        assert body["current_version_no"] == 1

    async def test_identical_body_patch_does_not_version(
        self, api: AsyncClient, audit_key: str
    ) -> None:
        policy_id = (await _create(api, audit_key))["id"]
        patched = await api.patch(
            f"/api/v1/policies/{policy_id}",
            json={"body": POLICY_BODY_V1},
            headers={"X-API-Key": audit_key},
        )
        assert patched.json()["current_version_no"] == 1

    async def test_empty_patch_is_422(self, api: AsyncClient, audit_key: str) -> None:
        policy_id = (await _create(api, audit_key))["id"]
        response = await api.patch(
            f"/api/v1/policies/{policy_id}", json={}, headers={"X-API-Key": audit_key}
        )
        assert response.status_code == 422

    async def test_soft_delete_hides_from_get_and_list(
        self, api: AsyncClient, audit_key: str
    ) -> None:
        policy_id = (await _create(api, audit_key))["id"]
        deleted = await api.delete(
            f"/api/v1/policies/{policy_id}", headers={"X-API-Key": audit_key}
        )
        assert deleted.status_code == 204

        assert (
            await api.get(f"/api/v1/policies/{policy_id}", headers={"X-API-Key": audit_key})
        ).status_code == 404
        listing = (await api.get("/api/v1/policies", headers={"X-API-Key": audit_key})).json()
        assert policy_id not in [item["id"] for item in listing["items"]]


class TestAuthz:
    async def test_read_scope_cannot_write(
        self, api: AsyncClient, owner_engine: AsyncEngine, two_orgs: tuple[int, int]
    ) -> None:
        read_key = await issue_key(owner_engine, two_orgs[0], ["read"])
        response = await api.post(
            "/api/v1/policies",
            json={"title": "x", "body": "y"},
            headers={"X-API-Key": read_key},
        )
        assert response.status_code == 403

    @pytest.mark.rls
    async def test_cross_tenant_policy_is_404_for_reads_and_writes(
        self,
        api: AsyncClient,
        audit_key: str,
        owner_engine: AsyncEngine,
        two_orgs: tuple[int, int],
    ) -> None:
        """B must not see, modify, or even confirm the existence of A's policy."""
        policy_id = (await _create(api, audit_key))["id"]
        key_b = await issue_key(owner_engine, two_orgs[1], ["audit"])

        get_resp = await api.get(f"/api/v1/policies/{policy_id}", headers={"X-API-Key": key_b})
        patch_resp = await api.patch(
            f"/api/v1/policies/{policy_id}",
            json={"title": "hijacked"},
            headers={"X-API-Key": key_b},
        )
        delete_resp = await api.delete(
            f"/api/v1/policies/{policy_id}", headers={"X-API-Key": key_b}
        )

        assert (get_resp.status_code, patch_resp.status_code, delete_resp.status_code) == (
            404,
            404,
            404,
        )
        # A's policy is intact:
        intact = await api.get(f"/api/v1/policies/{policy_id}", headers={"X-API-Key": audit_key})
        assert intact.status_code == 200
        assert intact.json()["title"] == "Funds Policy"
