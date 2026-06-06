"""Temporal vector search over HTTP + the HNSW index proof.

FakeEmbeddings = token-overlap vectors, so ranking assertions are about
vocabulary overlap — and the TEMPORAL filter does the real discriminating:
the same query returns different law for different as-of dates.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import issue_key

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

SETTLEMENT_QUERY = (
    "retail digital payment accounts must settle transit funds within maximum window business days"
)
R1 = "Regulation 12-B(4)"
R2 = "Regulation 12-B(4) (as amended)"


@pytest.fixture
async def read_key(owner_engine: AsyncEngine, two_orgs: tuple[int, int]) -> str:
    return await issue_key(owner_engine, two_orgs[0], ["read"])


async def _search(api: AsyncClient, key: str, **overrides: object) -> dict:  # type: ignore[type-arg]
    body: dict[str, object] = {
        "query": SETTLEMENT_QUERY,
        "jurisdiction": "PK",
        "as_of_date": "2026-06-06",
        "top_k": 8,
    }
    body.update(overrides)
    response = await api.post("/api/v1/regulatory/search", json=body, headers={"X-API-Key": key})
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


class TestTemporalSearch:
    async def test_post_amendment_returns_new_rule_not_old(
        self, seeded_corpus: None, api: AsyncClient, read_key: str
    ) -> None:
        body = await _search(api, read_key, as_of_date="2026-06-06")
        citations = [item["legal_citation"] for item in body["items"]]
        assert citations[0] == R2  # the 3-day amendment ranks first
        assert R1 not in citations  # the superseded 7-day rule is gone

    async def test_same_query_before_amendment_returns_old_rule(
        self, seeded_corpus: None, api: AsyncClient, read_key: str
    ) -> None:
        body = await _search(api, read_key, as_of_date="2025-01-01")
        citations = [item["legal_citation"] for item in body["items"]]
        assert citations[0] == R1
        assert R2 not in citations

    async def test_scores_are_similarity_descending(
        self, seeded_corpus: None, api: AsyncClient, read_key: str
    ) -> None:
        body = await _search(api, read_key)
        scores = [item["score"] for item in body["items"] if item["score"] is not None]
        assert scores == sorted(scores, reverse=True)
        assert all(0.0 <= score <= 1.0 for score in scores)

    async def test_alien_vocabulary_yields_single_weak_match(
        self, seeded_corpus: None, api: AsyncClient, read_key: str
    ) -> None:
        body = await _search(api, read_key, query="zebra quantum espresso paradox holiday")
        assert len(body["items"]) == 1
        assert body["items"][0]["weak_match"] is True

    async def test_citation_mention_promotes_exact_chunk(
        self, seeded_corpus: None, api: AsyncClient, read_key: str
    ) -> None:
        body = await _search(
            api, read_key, query="What does Regulation 7(2) require for float income?"
        )
        exact = [item for item in body["items"] if item["source"] == "citation"]
        assert any(item["legal_citation"] == "Regulation 7(2)" for item in exact)

    async def test_requires_auth_and_validates_body(
        self, seeded_corpus: None, api: AsyncClient, read_key: str
    ) -> None:
        unauthed = await api.post(
            "/api/v1/regulatory/search", json={"query": "x", "jurisdiction": "PK"}
        )
        assert unauthed.status_code == 401

        invalid = await api.post(
            "/api/v1/regulatory/search",
            json={"query": "ab", "jurisdiction": "PK"},  # below min_length
            headers={"X-API-Key": read_key},
        )
        assert invalid.status_code == 422


class TestHnswIndex:
    async def test_ann_query_uses_hnsw_index(
        self, seeded_corpus: None, owner_engine: AsyncEngine
    ) -> None:
        """With seqscan disabled, the planner must pick the HNSW index —
        proving it exists, matches the operator class, and is usable."""
        from chronosguard.providers import FakeEmbeddings

        [query_vector] = await FakeEmbeddings().embed(["settle funds"])
        literal = "[" + ",".join(f"{component:.6f}" for component in query_vector) + "]"

        async with owner_engine.connect() as conn:
            await conn.execute(text("SET LOCAL enable_seqscan = off"))
            plan_rows = await conn.execute(
                text(
                    "EXPLAIN (FORMAT TEXT) "  # noqa: S608 — literal is a locally built numeric vector
                    "SELECT id FROM regulatory_chunks WHERE embedding IS NOT NULL "
                    f"ORDER BY embedding <=> '{literal}'::vector LIMIT 5"
                )
            )
            plan = "\n".join(row[0] for row in plan_rows.fetchall())
        assert "ix_chunks_embedding_hnsw" in plan
