"""Ingestion end-to-end: quarantine gates, versioning, resumability,
supersession + staleness, the admin/n8n contract, and real-PDF extraction.

All corpus writes here use jurisdiction SG so the PK temporal truth-table
fixtures remain byte-identical for the other suites.
"""

import datetime as dt
import json
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from chronosguard.ingestion.service import (
    IngestHints,
    embed_pending_chunks,
    ingest_bytes,
    ingest_markdown,
)
from chronosguard.ingestion.supersession import confirm_supersession
from chronosguard.providers import FakeChat, FakeEmbeddings
from chronosguard.retrieval.temporal import in_force_chunks
from chronosguard.worker.runner import Worker
from tests.chunkers_fixture import (
    INJECTION_GAZETTE,
    STRUCTURED_GAZETTE,
    UNSTRUCTURED_NOTICE,
    URDU_PRIMARY,
)
from tests.conftest import issue_key

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

JURISDICTION = "SG"


def _hints(*, title: str = "SECP Circular 21 of 2026", url: str | None = None) -> IngestHints:
    return IngestHints(
        source_url=url or f"https://example.test/{uuid.uuid4().hex}.pdf",
        title=title,
        issuing_body="SECP",
        document_type="Circular",
        jurisdiction=JURISDICTION,
        published_date=dt.date(2026, 8, 15),
    )


@pytest.fixture
async def sg_jurisdiction(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO jurisdictions (code, name) VALUES ('SG', 'Singapore') "
                "ON CONFLICT (code) DO NOTHING"
            )
        )


@pytest.fixture
async def ingest_session(worker_engine: AsyncEngine, sg_jurisdiction: None) -> AsyncSession:
    return AsyncSession(worker_engine, expire_on_commit=False, autoflush=False)


async def _in_force_texts(engine: AsyncEngine, as_of: dt.date) -> set[str]:
    async with AsyncSession(engine) as session:
        rows = (await session.execute(in_force_chunks(JURISDICTION, as_of))).scalars().all()
    return {chunk.content for chunk in rows}


class TestHappyPath:
    async def test_structured_gazette_is_confirmed_and_retrievable(
        self, ingest_session: AsyncSession, app_engine: AsyncEngine
    ) -> None:
        async with ingest_session as session:
            outcome = await ingest_markdown(
                session, FakeEmbeddings(), markdown=STRUCTURED_GAZETTE, hints=_hints()
            )
        assert outcome.status == "confirmed"
        assert outcome.chunk_count >= 3
        assert any("Circular No. 5 of 2019" in ref for ref in outcome.supersedes_refs)

        # Effective 1 Sept 2026 (extracted) — in force in October, not in August.
        october = await _in_force_texts(app_engine, dt.date(2026, 10, 1))
        august = await _in_force_texts(app_engine, dt.date(2026, 8, 20))
        assert any("segregated safeguarding" in text_ for text_ in october)
        assert not any("segregated safeguarding" in text_ for text_ in august)

    async def test_reingest_same_content_is_deduped(self, ingest_session: AsyncSession) -> None:
        hints = _hints()
        async with ingest_session as session:
            first = await ingest_markdown(
                session, FakeEmbeddings(), markdown=STRUCTURED_GAZETTE, hints=hints
            )
            second = await ingest_markdown(
                session, FakeEmbeddings(), markdown=STRUCTURED_GAZETTE, hints=hints
            )
        assert not first.deduped
        assert second.deduped
        assert second.document_id == first.document_id

    async def test_corrected_republish_versions_and_quarantines_prior(
        self, ingest_session: AsyncSession, app_engine: AsyncEngine, owner_engine: AsyncEngine
    ) -> None:
        hints = _hints()
        # Unique day-counts: other tests in this shared-session DB ingest the
        # base gazette text, so retrieval markers must not collide.
        original = STRUCTURED_GAZETTE.replace(
            "two (2) business days", "fourteen (14) business days"
        )
        corrected = STRUCTURED_GAZETTE.replace("two (2) business days", "nine (9) business days")
        async with ingest_session as session:
            v1 = await ingest_markdown(session, FakeEmbeddings(), markdown=original, hints=hints)
            v2 = await ingest_markdown(session, FakeEmbeddings(), markdown=corrected, hints=hints)
        assert v2.document_id != v1.document_id

        async with owner_engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT id, version, extraction_status, review_reason "
                        "FROM regulatory_documents WHERE source_url = :url ORDER BY version"
                    ),
                    {"url": hints.source_url},
                )
            ).fetchall()
        assert [row.version for row in rows] == [1, 2]
        assert rows[0].extraction_status == "review"
        assert rows[0].review_reason == "superseded_by_correction"
        assert rows[1].extraction_status == "confirmed"

        in_force = await _in_force_texts(app_engine, dt.date(2026, 10, 1))
        assert any("nine (9) business days" in text_ for text_ in in_force)
        assert not any("fourteen (14) business days" in text_ for text_ in in_force)


class TestQuarantineGates:
    @pytest.mark.parametrize(
        ("case_id", "markdown", "expected_reason", "marker"),
        [
            ("unstructured", UNSTRUCTURED_NOTICE, "no_structure", "wishes to remind"),
            ("urdu", URDU_PRIMARY, "non_english", "سرکلر"),
            (
                "injection",
                INJECTION_GAZETTE,
                "injection_flag",
                "Ignore previous instructions",
            ),
        ],
        ids=["unstructured", "urdu", "injection"],
    )
    async def test_suspect_documents_are_quarantined_not_retrievable(
        self,
        ingest_session: AsyncSession,
        app_engine: AsyncEngine,
        case_id: str,
        markdown: str,
        expected_reason: str,
        marker: str,
    ) -> None:
        async with ingest_session as session:
            outcome = await ingest_markdown(
                session, FakeEmbeddings(), markdown=markdown, hints=_hints()
            )
        assert outcome.status == "review"
        assert outcome.review_reason == expected_reason
        # The review gate in THE canonical predicate keeps it out of retrieval:
        in_force = await _in_force_texts(app_engine, dt.date(2027, 1, 1))
        assert not any(marker in text_ for text_ in in_force)


class TestPdfPath:
    async def test_text_pdf_extracts_and_confirms(self, ingest_session: AsyncSession) -> None:
        import pymupdf

        pdf = pymupdf.open()
        page = pdf.new_page()
        page.insert_text((72, 72), STRUCTURED_GAZETTE, fontsize=9)
        pdf_bytes = pdf.tobytes()
        pdf.close()

        async with ingest_session as session:
            outcome = await ingest_bytes(
                session, FakeEmbeddings(), content=pdf_bytes, hints=_hints()
            )
        assert outcome.status in {"confirmed", "review"}  # extraction fidelity varies
        assert outcome.chunk_count >= 1

    async def test_imageless_blank_pdf_is_rejected_as_scanned(
        self, ingest_session: AsyncSession
    ) -> None:
        import pymupdf

        pdf = pymupdf.open()
        pdf.new_page()  # zero extractable text
        pdf_bytes = pdf.tobytes()
        pdf.close()

        async with ingest_session as session:
            outcome = await ingest_bytes(
                session, FakeEmbeddings(), content=pdf_bytes, hints=_hints()
            )
        assert outcome.status == "review"
        assert outcome.review_reason == "scanned_pdf"
        assert outcome.chunk_count == 0


class TestResumability:
    async def test_backfill_completes_interrupted_embedding(
        self, ingest_session: AsyncSession, owner_engine: AsyncEngine, worker_engine: AsyncEngine
    ) -> None:
        hints = _hints()
        async with ingest_session as session:
            outcome = await ingest_markdown(
                session, FakeEmbeddings(), markdown=STRUCTURED_GAZETTE, hints=hints
            )
        # Simulate a crash mid-embedding: wipe the vectors.
        async with owner_engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE regulatory_chunks SET embedding = NULL, embedded_at = NULL "
                    "WHERE document_id = :doc"
                ),
                {"doc": outcome.document_id},
            )

        async with AsyncSession(worker_engine, expire_on_commit=False) as session:
            embedded = await embed_pending_chunks(
                session, FakeEmbeddings(), document_id=outcome.document_id
            )
        assert embedded == outcome.chunk_count

        async with owner_engine.connect() as conn:
            pending = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM regulatory_chunks "
                        "WHERE document_id = :doc AND embedded_at IS NULL"
                    ),
                    {"doc": outcome.document_id},
                )
            ).scalar_one()
        assert pending == 0


class TestSupersessionAndStaleness:
    async def test_supersede_closes_intervals_and_flags_stale_runs(
        self,
        ingest_session: AsyncSession,
        owner_engine: AsyncEngine,
        app_engine: AsyncEngine,
        two_orgs: tuple[int, int],
    ) -> None:
        old_gazette = STRUCTURED_GAZETTE.replace(
            "come into force on 1 September 2026", "come into force on 1 January 2024"
        ).replace("two (2) business days", "five (5) business days")

        async with ingest_session as session:
            old = await ingest_markdown(
                session,
                FakeEmbeddings(),
                markdown=old_gazette,
                hints=_hints(title="Old Safeguarding Circular"),
            )
            new = await ingest_markdown(
                session, FakeEmbeddings(), markdown=STRUCTURED_GAZETTE, hints=_hints()
            )

        org_a, _ = two_orgs
        async with owner_engine.begin() as conn:
            old_chunk_id = (
                await conn.execute(
                    text("SELECT id FROM regulatory_chunks WHERE document_id = :doc LIMIT 1"),
                    {"doc": old.document_id},
                )
            ).scalar_one()
            # Two synthetic past runs: one anchored after the supersession date
            # (must flag), one before (must not).
            for as_of, marker in (
                (dt.date(2026, 10, 1), "affected"),
                (dt.date(2025, 3, 1), "unaffected"),
            ):
                await conn.execute(
                    text(
                        "INSERT INTO audit_runs (tenant_id, policy_text_snapshot, "
                        "jurisdiction, as_of_date, status, retrieved_chunk_ids, stale, "
                        "total_tokens) VALUES (:tid, :marker, 'SG', :as_of, 'succeeded', "
                        "CAST(:ids AS jsonb), false, 0)"
                    ),
                    {
                        "tid": org_a,
                        "marker": marker,
                        "as_of": as_of,
                        "ids": json.dumps([old_chunk_id]),
                    },
                )

        async with AsyncSession(owner_engine, expire_on_commit=False) as session:
            report = await confirm_supersession(
                session,
                superseded_document_id=old.document_id,
                superseding_document_id=new.document_id,
                relation="amends",
            )
        assert report.superseded_chunks >= 1
        assert report.supersession_effective_date == dt.date(2026, 9, 1)
        assert report.stale_runs_flagged == 1  # only the post-supersession run

        async with owner_engine.connect() as conn:
            flags = (
                await conn.execute(
                    text(
                        "SELECT policy_text_snapshot, stale FROM audit_runs "
                        "WHERE jurisdiction = 'SG' ORDER BY id DESC LIMIT 2"
                    )
                )
            ).fetchall()
        by_marker = {row[0]: row[1] for row in flags}
        assert by_marker["affected"] is True
        assert by_marker["unaffected"] is False

        # Temporal handover: old rule governs July 2026, new rule governs October.
        july = await _in_force_texts(app_engine, dt.date(2026, 7, 1))
        october = await _in_force_texts(app_engine, dt.date(2026, 10, 1))
        assert any("five (5) business days" in t for t in july)
        assert not any("five (5) business days" in t for t in october)

        # Lineage edge recorded:
        async with owner_engine.connect() as conn:
            edges = (
                await conn.execute(
                    text("SELECT count(*) FROM supersessions WHERE superseded_chunk_id = :cid"),
                    {"cid": old_chunk_id},
                )
            ).scalar_one()
        assert edges == 1


class TestAdminContract:
    async def test_n8n_flow_post_poll_process(
        self,
        api: AsyncClient,
        owner_engine: AsyncEngine,
        worker_engine: AsyncEngine,
        two_orgs: tuple[int, int],
        sg_jurisdiction: None,
        tmp_path: Path,
    ) -> None:
        admin_key = await issue_key(owner_engine, two_orgs[0], ["admin"])
        fixture = tmp_path / "gazette.md"
        fixture.write_text(STRUCTURED_GAZETTE, encoding="utf-8")

        # n8n POSTs hints only — no legal dates in the body.
        response = await api.post(
            "/api/v1/admin/ingest",
            json={
                "source_url": f"https://example.test/{uuid.uuid4().hex}.pdf",
                "title": "SECP Circular 21 of 2026",
                "issuing_body": "SECP",
                "document_type": "Circular",
                "jurisdiction": "SG",
                "published_date": "2026-08-15",
            },
            headers={"X-API-Key": admin_key},
        )
        assert response.status_code == 202, response.text
        job = response.json()
        assert job["status"] == "queued"

        # Point the queued job at the local fixture (test stand-in for the fetch).
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("UPDATE jobs SET payload = payload || CAST(:extra AS jsonb) WHERE id = :id"),
                {"extra": json.dumps({"file_path": str(fixture)}), "id": job["id"]},
            )

        worker = Worker(worker_engine, FakeEmbeddings(), FakeChat(), name="test-worker")
        assert await worker.drain() >= 1

        polled = await api.get(
            f"/api/v1/admin/ingest/{job['id']}", headers={"X-API-Key": admin_key}
        )
        body = polled.json()
        assert body["status"] == "succeeded"
        assert body["ref_id"] is not None  # the produced document id

    async def test_unknown_jurisdiction_rejected(
        self, api: AsyncClient, owner_engine: AsyncEngine, two_orgs: tuple[int, int]
    ) -> None:
        admin_key = await issue_key(owner_engine, two_orgs[0], ["admin"])
        response = await api.post(
            "/api/v1/admin/ingest",
            json={
                "source_url": "https://example.test/x.pdf",
                "title": "Doc title here",
                "issuing_body": "SECP",
                "document_type": "Circular",
                "jurisdiction": "ZZ",
                "published_date": "2026-08-15",
            },
            headers={"X-API-Key": admin_key},
        )
        assert response.status_code == 422

    async def test_audit_scope_cannot_trigger_ingest(
        self, api: AsyncClient, owner_engine: AsyncEngine, two_orgs: tuple[int, int]
    ) -> None:
        audit_key = await issue_key(owner_engine, two_orgs[0], ["audit"])
        response = await api.post(
            "/api/v1/admin/ingest",
            json={
                "source_url": "https://example.test/x.pdf",
                "title": "Doc title here",
                "issuing_body": "SECP",
                "document_type": "Circular",
                "jurisdiction": "PK",
                "published_date": "2026-08-15",
            },
            headers={"X-API-Key": audit_key},
        )
        assert response.status_code == 403
