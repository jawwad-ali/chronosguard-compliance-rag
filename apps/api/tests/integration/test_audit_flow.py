"""The core loop, end-to-end: POST 202 → worker → poll → grounded findings.

This is the spec's PocketPay demo as an executable test: the same policy is a
HIGH violation as of June 2026 (3-day amendment in force) and compliant as of
January 2025 (old 7-day rule governed). Plus: grounding gate, partial-failure
semantics, job retry/lease recovery, and worker-path RLS proofs.
"""

import datetime as dt
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine

from chronosguard.audit.schema import ClauseFinding, ClauseVerdict, RiskLevel, Verdict
from chronosguard.providers import FakeChat, FakeEmbeddings
from chronosguard.worker.runner import Worker
from tests.conftest import issue_key

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

POCKETPAY_POLICY = (
    "PocketPay will hold user funds for up to 7 business days before clearing.\n\n"
    "Customer KYC records are retained for 5 years after account closure."
)


@pytest.fixture
async def audit_key(owner_engine: AsyncEngine, two_orgs: tuple[int, int]) -> str:
    return await issue_key(owner_engine, two_orgs[0], ["audit"])


def make_worker(engine: AsyncEngine, chat: FakeChat | None = None) -> Worker:
    return Worker(engine, FakeEmbeddings(), chat or FakeChat(), name="test-worker")


async def _post_audit(
    api: AsyncClient,
    key: str,
    *,
    as_of: str,
    policy_text: str = POCKETPAY_POLICY,
    jurisdiction: str = "PK",
) -> dict[str, Any]:
    response = await api.post(
        "/api/v1/audits",
        json={"policy_text": policy_text, "jurisdiction": jurisdiction, "as_of_date": as_of},
        headers={"X-API-Key": key},
    )
    assert response.status_code == 202, response.text
    assert response.headers["Location"].startswith("/api/v1/audits/")
    body: dict[str, Any] = response.json()
    assert body["status"] == "queued"
    return body


async def _get_run(api: AsyncClient, key: str, run_id: int) -> dict[str, Any]:
    response = await api.get(f"/api/v1/audits/{run_id}", headers={"X-API-Key": key})
    assert response.status_code == 200
    return response.json()  # type: ignore[no-any-return]


class TestPocketPayDemo:
    async def test_violation_found_after_amendment(
        self,
        seeded_corpus: None,
        api: AsyncClient,
        audit_key: str,
        worker_engine: AsyncEngine,
    ) -> None:
        run = await _post_audit(api, audit_key, as_of="2026-06-06")
        assert await make_worker(worker_engine).drain() >= 1

        finished = await _get_run(api, audit_key, run["id"])
        assert finished["status"] == "succeeded"
        assert finished["verdict"] == "VIOLATIONS_FOUND"
        assert finished["coverage"]["violation"] >= 1
        assert finished["model"] == "fake-chat-v1"
        assert finished["finished_at"] is not None

        findings = (
            await api.get(f"/api/v1/audits/{run['id']}/findings", headers={"X-API-Key": audit_key})
        ).json()
        assert findings["total"] >= 1
        finding = findings["items"][0]
        assert finding["risk_level"] == "HIGH"
        assert finding["citation"] == "Regulation 12-B(4) (as amended)"
        assert finding["source_url"] == "https://example-secp.gov.pk/sro/1234-2026.pdf"
        assert "three (3) business days" in finding["grounding_quote"]
        assert "7 business days" in finding["offending_policy_text"]
        assert finding["source_chunk_id"] is not None  # citation tracing for the UI

    async def test_same_policy_compliant_before_amendment(
        self,
        seeded_corpus: None,
        api: AsyncClient,
        audit_key: str,
        worker_engine: AsyncEngine,
    ) -> None:
        """Point-in-time: in January 2025 the 7-day rule governed — no violation."""
        run = await _post_audit(api, audit_key, as_of="2025-01-01")
        await make_worker(worker_engine).drain()

        finished = await _get_run(api, audit_key, run["id"])
        assert finished["status"] == "succeeded"
        assert finished["verdict"] == "COMPLIANT"
        assert finished["coverage"]["violation"] == 0

    async def test_run_snapshots_inputs_for_reproducibility(
        self,
        seeded_corpus: None,
        api: AsyncClient,
        audit_key: str,
        worker_engine: AsyncEngine,
        owner_engine: AsyncEngine,
    ) -> None:
        run = await _post_audit(api, audit_key, as_of="2026-06-06")
        await make_worker(worker_engine).drain()
        async with owner_engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT policy_text_snapshot, clauses_snapshot, retrieved_chunk_ids "
                        "FROM audit_runs WHERE id = :id"
                    ),
                    {"id": run["id"]},
                )
            ).one()
        assert row.policy_text_snapshot == POCKETPAY_POLICY
        assert len(row.clauses_snapshot) == 2
        assert len(row.retrieved_chunk_ids) >= 1


class TestHonestVerdicts:
    async def test_no_applicable_law_is_insufficient_never_compliant(
        self,
        seeded_corpus: None,
        api: AsyncClient,
        audit_key: str,
        worker_engine: AsyncEngine,
        owner_engine: AsyncEngine,
    ) -> None:
        async with owner_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO jurisdictions (code, name) VALUES ('EU', 'European Union') "
                    "ON CONFLICT (code) DO NOTHING"
                )
            )
        run = await _post_audit(api, audit_key, as_of="2026-06-06", jurisdiction="EU")
        await make_worker(worker_engine).drain()

        finished = await _get_run(api, audit_key, run["id"])
        assert finished["verdict"] == "INSUFFICIENT_EVIDENCE"
        assert finished["coverage"]["insufficient_evidence"] >= 1

    async def test_unknown_jurisdiction_rejected_upfront(
        self, seeded_corpus: None, api: AsyncClient, audit_key: str
    ) -> None:
        response = await api.post(
            "/api/v1/audits",
            json={"policy_text": "x", "jurisdiction": "XX", "as_of_date": "2026-06-06"},
            headers={"X-API-Key": audit_key},
        )
        assert response.status_code == 422

    async def test_fabricated_quote_is_dropped_by_grounding_gate(
        self,
        seeded_corpus: None,
        api: AsyncClient,
        audit_key: str,
        worker_engine: AsyncEngine,
    ) -> None:
        def fabricating_script(payload: dict[str, Any]) -> ClauseVerdict:
            return ClauseVerdict(
                verdict=Verdict.VIOLATION,
                findings=[
                    ClauseFinding(
                        ref_id=payload["excerpts"][0]["ref_id"],
                        grounding_quote="funds must be settled instantly upon receipt",
                        risk_level=RiskLevel.HIGH,
                        rationale="fabricated",
                        suggested_fix="n/a",
                    )
                ],
                confidence=0.99,
            )

        run = await _post_audit(api, audit_key, as_of="2026-06-06")
        await make_worker(worker_engine, FakeChat(script=fabricating_script)).drain()

        finished = await _get_run(api, audit_key, run["id"])
        # Every claimed violation failed grounding ⇒ downgraded, zero findings.
        assert finished["verdict"] == "INSUFFICIENT_EVIDENCE"
        findings = (
            await api.get(f"/api/v1/audits/{run['id']}/findings", headers={"X-API-Key": audit_key})
        ).json()
        assert findings["total"] == 0

    async def test_clause_llm_failure_yields_partial_never_compliant(
        self,
        seeded_corpus: None,
        api: AsyncClient,
        audit_key: str,
        worker_engine: AsyncEngine,
    ) -> None:
        def exploding_script(payload: dict[str, Any]) -> ClauseVerdict:
            msg = "simulated provider outage"
            raise RuntimeError(msg)

        run = await _post_audit(
            api, audit_key, as_of="2026-06-06", policy_text="Single clause about settlements."
        )
        await make_worker(worker_engine, FakeChat(script=exploding_script)).drain()

        finished = await _get_run(api, audit_key, run["id"])
        assert finished["status"] == "partial"
        assert finished["verdict"] is None
        assert finished["coverage"]["error"] == 1


class TestJobMachinery:
    async def test_total_pipeline_failure_exhausts_retries_then_fails_run(
        self,
        seeded_corpus: None,
        api: AsyncClient,
        audit_key: str,
        worker_engine: AsyncEngine,
    ) -> None:
        class FailingEmbedder:
            model = "failing"
            dims = 1536

            async def embed(self, texts: list[str]) -> list[list[float]]:
                msg = "embeddings hard down"
                raise RuntimeError(msg)

        run = await _post_audit(api, audit_key, as_of="2026-06-06")
        worker = Worker(worker_engine, FailingEmbedder(), FakeChat(), name="test-worker")
        await worker.drain()  # claims, fails, requeues, reclaims… until attempts exhausted

        finished = await _get_run(api, audit_key, run["id"])
        assert finished["status"] == "failed"
        assert finished["error"] == "job retries exhausted"

    async def test_reaper_requeues_expired_lease(
        self, owner_engine: AsyncEngine, worker_engine: AsyncEngine, two_orgs: tuple[int, int]
    ) -> None:
        async with owner_engine.begin() as conn:
            job_id = (
                await conn.execute(
                    text(
                        "INSERT INTO jobs (kind, status, attempts, max_attempts, locked_at, "
                        "locked_by) VALUES ('audit', 'running', 1, 3, now() - interval "
                        "'20 minutes', 'dead-worker') RETURNING id"
                    )
                )
            ).scalar_one()

        reaped = await make_worker(worker_engine).reap()
        assert reaped == 1

        async with owner_engine.begin() as conn:
            status = (
                await conn.execute(text("SELECT status FROM jobs WHERE id = :id"), {"id": job_id})
            ).scalar_one()
            await conn.execute(text("DELETE FROM jobs WHERE id = :id"), {"id": job_id})
        assert status == "queued"

    async def test_reaper_fails_job_with_exhausted_attempts(
        self, owner_engine: AsyncEngine, worker_engine: AsyncEngine, two_orgs: tuple[int, int]
    ) -> None:
        async with owner_engine.begin() as conn:
            job_id = (
                await conn.execute(
                    text(
                        "INSERT INTO jobs (kind, status, attempts, max_attempts, locked_at, "
                        "locked_by) VALUES ('audit', 'running', 3, 3, now() - interval "
                        "'20 minutes', 'dead-worker') RETURNING id"
                    )
                )
            ).scalar_one()

        await make_worker(worker_engine).reap()

        async with owner_engine.begin() as conn:
            status = (
                await conn.execute(text("SELECT status FROM jobs WHERE id = :id"), {"id": job_id})
            ).scalar_one()
            await conn.execute(text("DELETE FROM jobs WHERE id = :id"), {"id": job_id})
        assert status == "failed"


class TestWorkerRls:
    @pytest.mark.rls
    async def test_tenant_b_cannot_see_a_runs_or_findings(
        self,
        seeded_corpus: None,
        api: AsyncClient,
        audit_key: str,
        owner_engine: AsyncEngine,
        worker_engine: AsyncEngine,
        two_orgs: tuple[int, int],
    ) -> None:
        run = await _post_audit(api, audit_key, as_of="2026-06-06")
        await make_worker(worker_engine).drain()

        key_b = await issue_key(owner_engine, two_orgs[1], ["audit"])
        run_resp = await api.get(f"/api/v1/audits/{run['id']}", headers={"X-API-Key": key_b})
        findings_resp = await api.get(
            f"/api/v1/audits/{run['id']}/findings", headers={"X-API-Key": key_b}
        )
        assert (run_resp.status_code, findings_resp.status_code) == (404, 404)

        listing = (await api.get("/api/v1/audits", headers={"X-API-Key": key_b})).json()
        assert listing["total"] == 0

    @pytest.mark.rls
    async def test_worker_cannot_write_findings_without_tenant_context(
        self,
        seeded_corpus: None,
        api: AsyncClient,
        audit_key: str,
        worker_engine: AsyncEngine,
    ) -> None:
        """FORCE RLS guards the worker path: no context ⇒ WITH CHECK rejects."""
        run = await _post_audit(api, audit_key, as_of="2026-06-06")
        await make_worker(worker_engine).drain()

        async with worker_engine.connect() as conn:
            with pytest.raises(ProgrammingError, match="row-level security"):
                await conn.execute(
                    text(
                        "INSERT INTO audit_findings (tenant_id, run_id, clause_index, "
                        "offending_policy_text, legal_rule_text, citation, source_url, "
                        "risk_level, grounding_quote, rationale, suggested_fix, confidence, "
                        "needs_review) VALUES (:tid, :rid, 0, 'x', 'y', 'c', 'u', 'HIGH', "
                        "'q', 'r', 's', 0.5, false)"
                    ),
                    {"tid": 1, "rid": run["id"]},
                )


class TestAuditValidation:
    async def test_both_policy_sources_rejected(
        self, seeded_corpus: None, api: AsyncClient, audit_key: str
    ) -> None:
        response = await api.post(
            "/api/v1/audits",
            json={
                "policy_id": 1,
                "policy_text": "also text",
                "jurisdiction": "PK",
            },
            headers={"X-API-Key": audit_key},
        )
        assert response.status_code == 422

    async def test_audit_of_stored_policy_links_version(
        self,
        seeded_corpus: None,
        api: AsyncClient,
        audit_key: str,
        worker_engine: AsyncEngine,
    ) -> None:
        created = await api.post(
            "/api/v1/policies",
            json={"title": "Stored", "body": POCKETPAY_POLICY},
            headers={"X-API-Key": audit_key},
        )
        policy_id = created.json()["id"]

        response = await api.post(
            "/api/v1/audits",
            json={"policy_id": policy_id, "jurisdiction": "PK", "as_of_date": "2026-06-06"},
            headers={"X-API-Key": audit_key},
        )
        assert response.status_code == 202
        run = response.json()
        assert run["policy_id"] == policy_id
        assert run["policy_version_id"] is not None

        await make_worker(worker_engine).drain()
        finished = await _get_run(api, audit_key, run["id"])
        assert finished["verdict"] == "VIOLATIONS_FOUND"

    async def test_read_scope_cannot_create_audits(
        self,
        seeded_corpus: None,
        api: AsyncClient,
        owner_engine: AsyncEngine,
        two_orgs: tuple[int, int],
    ) -> None:
        read_key = await issue_key(owner_engine, two_orgs[0], ["read"])
        response = await api.post(
            "/api/v1/audits",
            json={"policy_text": "x", "jurisdiction": "PK"},
            headers={"X-API-Key": read_key},
        )
        assert response.status_code == 403

    async def test_as_of_defaults_to_today(
        self, seeded_corpus: None, api: AsyncClient, audit_key: str
    ) -> None:
        response = await api.post(
            "/api/v1/audits",
            json={"policy_text": "Some clause.", "jurisdiction": "PK"},
            headers={"X-API-Key": audit_key},
        )
        assert response.json()["as_of_date"] == dt.datetime.now(dt.UTC).date().isoformat()
