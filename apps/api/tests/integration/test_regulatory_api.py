"""Corpus browse endpoints: confirmed-only visibility, filters, pagination."""

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import issue_key

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


@pytest.fixture
async def read_key(owner_engine: AsyncEngine, two_orgs: tuple[int, int]) -> str:
    return await issue_key(owner_engine, two_orgs[0], ["read"])


class TestDocumentListing:
    async def test_lists_only_confirmed_documents(
        self, seeded_corpus: None, api: AsyncClient, read_key: str
    ) -> None:
        response = await api.get("/api/v1/regulatory/documents", headers={"X-API-Key": read_key})
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 5  # six seeded, one in review
        titles = {doc["title"] for doc in body["items"]}
        assert not any("UNDER REVIEW" in title for title in titles)

    async def test_filters_by_issuing_body(
        self, seeded_corpus: None, api: AsyncClient, read_key: str
    ) -> None:
        response = await api.get(
            "/api/v1/regulatory/documents",
            params={"issuing_body": "SBP"},
            headers={"X-API-Key": read_key},
        )
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["issuing_body"] == "SBP"

    async def test_pagination_envelope_and_ceiling(
        self, seeded_corpus: None, api: AsyncClient, read_key: str
    ) -> None:
        response = await api.get(
            "/api/v1/regulatory/documents",
            params={"limit": 2, "offset": 2},
            headers={"X-API-Key": read_key},
        )
        body = response.json()
        assert body["limit"] == 2
        assert body["offset"] == 2
        assert len(body["items"]) == 2
        assert body["total"] == 5

        over_limit = await api.get(
            "/api/v1/regulatory/documents",
            params={"limit": 5000},
            headers={"X-API-Key": read_key},
        )
        assert over_limit.status_code == 422  # hard ceiling enforced

    async def test_requires_auth(self, seeded_corpus: None, api: AsyncClient) -> None:
        assert (await api.get("/api/v1/regulatory/documents")).status_code == 401


class TestDocumentDetail:
    async def _confirmed_doc_id(self, api: AsyncClient, key: str) -> int:
        listing = await api.get(
            "/api/v1/regulatory/documents",
            params={"issuing_body": "SBP"},
            headers={"X-API-Key": key},
        )
        return int(listing.json()["items"][0]["id"])

    async def test_detail_includes_chunk_count_and_source(
        self, seeded_corpus: None, api: AsyncClient, read_key: str
    ) -> None:
        doc_id = await self._confirmed_doc_id(api, read_key)
        response = await api.get(
            f"/api/v1/regulatory/documents/{doc_id}", headers={"X-API-Key": read_key}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["chunk_count"] == 1
        assert body["source_url"].startswith("https://")

    async def test_review_document_is_404_not_403(
        self,
        seeded_corpus: None,
        api: AsyncClient,
        read_key: str,
        owner_engine: AsyncEngine,
    ) -> None:
        async with owner_engine.connect() as conn:
            review_id = (
                await conn.execute(
                    text(
                        "SELECT id FROM regulatory_documents "
                        "WHERE extraction_status = 'review' LIMIT 1"
                    )
                )
            ).scalar_one()
        response = await api.get(
            f"/api/v1/regulatory/documents/{review_id}", headers={"X-API-Key": read_key}
        )
        assert response.status_code == 404  # unconfirmed is invisible, not forbidden

    async def test_chunks_listing_ordered_with_temporal_fields(
        self, seeded_corpus: None, api: AsyncClient, read_key: str
    ) -> None:
        doc_id = await self._confirmed_doc_id(api, read_key)
        response = await api.get(
            f"/api/v1/regulatory/documents/{doc_id}/chunks", headers={"X-API-Key": read_key}
        )
        assert response.status_code == 200
        chunk = response.json()["items"][0]
        assert chunk["legal_citation"] == "Para 4(a)"
        assert chunk["effective_date"] == "2023-07-15"
        assert chunk["expiration_date"] is None
        assert "embedding" not in chunk  # vectors never leave the API
