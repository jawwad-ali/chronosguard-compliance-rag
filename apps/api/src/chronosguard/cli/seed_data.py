"""Development/test seed corpus (docs/ARCHITECTURE.md §8.3).

Six documents engineered to exercise every temporal edge the truth-table
tests assert on. Idempotent: re-running is a no-op (keyed on source_url).
Embeddings come from the deterministic FakeEmbeddings — seeding never costs
OpenAI money; `chronos seed --real-embeddings` is a later upgrade.
"""

import datetime as dt
import hashlib
from dataclasses import dataclass, field

from chronosguard.models import (
    EffectiveDateSource,
    ExtractionStatus,
    SupersessionRelation,
)

SEED_JURISDICTION = ("PK", "Pakistan")
SEED_ORGS = (("PocketPay", "PK"), ("Acme Corp", "PK"))


@dataclass(frozen=True)
class SeedChunk:
    legal_citation: str
    heading_path: str
    content: str
    effective_date: dt.date
    expiration_date: dt.date | None = None
    effective_date_source: str = EffectiveDateSource.EXTRACTED.value


@dataclass(frozen=True)
class SeedDocument:
    key: str  # stable handle used by tests/supersession wiring
    title: str
    issuing_body: str
    document_type: str
    source_url: str
    published_date: dt.date
    chunks: list[SeedChunk] = field(default_factory=list)
    extraction_status: str = ExtractionStatus.CONFIRMED.value
    review_reason: str | None = None


@dataclass(frozen=True)
class SeedSupersession:
    superseded_doc_key: str
    superseding_doc_key: str
    relation: str
    effective_date: dt.date


def embed_text_for(chunk: SeedChunk) -> str:
    """Breadcrumb-prefixed text — what actually gets embedded (recall win)."""
    return f"[{chunk.heading_path}] {chunk.content}"


def content_hash_for(doc: SeedDocument) -> str:
    joined = "\n\n".join(chunk.content for chunk in doc.chunks)
    return hashlib.sha256(joined.encode()).hexdigest()


SEED_DOCUMENTS: list[SeedDocument] = [
    SeedDocument(
        key="settlement_v1",
        title="SECP SRO 450(I)/2023 — Digital Payment Settlement Rules",
        issuing_body="SECP",
        document_type="SRO",
        source_url="https://example-secp.gov.pk/sro/450-2023.pdf",
        published_date=dt.date(2023, 11, 15),
        chunks=[
            SeedChunk(
                legal_citation="Regulation 12-B(4)",
                heading_path="Part II > Chapter 1 > Regulation 12-B",
                content=(
                    "All retail digital payment accounts must settle transit funds within a "
                    "maximum window of seven (7) business days of transaction initiation. "
                    "Licensed operators holding customer funds beyond this window shall be "
                    "liable to penalty under Section 41."
                ),
                effective_date=dt.date(2024, 1, 1),
                expiration_date=dt.date(2026, 6, 1),  # closed by the 2026 amendment
            )
        ],
    ),
    SeedDocument(
        key="settlement_v2",
        title="SECP SRO 1234(I)/2026 — Settlement Rules (Amendment)",
        issuing_body="SECP",
        document_type="SRO",
        source_url="https://example-secp.gov.pk/sro/1234-2026.pdf",
        published_date=dt.date(2026, 5, 20),
        chunks=[
            SeedChunk(
                legal_citation="Regulation 12-B(4) (as amended)",
                heading_path="Part II > Chapter 1 > Regulation 12-B",
                content=(
                    "Regulation 12-B(4) is amended as follows: all retail digital payment "
                    "accounts must settle transit funds within a strict maximum window of "
                    "three (3) business days. Holding customer funds beyond seventy-two (72) "
                    "hours requires prior written approval of the Commission."
                ),
                effective_date=dt.date(2026, 6, 1),
            )
        ],
    ),
    SeedDocument(
        key="kyc_retention",
        title="SBP BPRD Circular No. 09 of 2023 — KYC Record Retention",
        issuing_body="SBP",
        document_type="Circular",
        source_url="https://example-sbp.org.pk/circulars/bprd-09-2023.pdf",
        published_date=dt.date(2023, 7, 1),
        chunks=[
            SeedChunk(
                legal_citation="Para 4(a)",
                heading_path="BPRD Circular 09/2023 > Para 4",
                content=(
                    "Banks and electronic money institutions shall retain all Know Your "
                    "Customer (KYC) records and customer due diligence documentation for a "
                    "minimum period of ten (10) years after termination of the business "
                    "relationship."
                ),
                effective_date=dt.date(2023, 7, 15),
            )
        ],
    ),
    SeedDocument(
        key="expired_relief",
        title="SECP Circular No. 05 of 2020 — Pandemic Filing Relief",
        issuing_body="SECP",
        document_type="Circular",
        source_url="https://example-secp.gov.pk/circulars/05-2020.pdf",
        published_date=dt.date(2019, 12, 28),
        chunks=[
            SeedChunk(
                legal_citation="Para 2",
                heading_path="Circular 05/2020 > Para 2",
                content=(
                    "In view of prevailing pandemic conditions, late filing penalties under "
                    "the Companies Act are waived for all listed entities until further "
                    "notice by the Commission."
                ),
                effective_date=dt.date(2020, 1, 1),
                expiration_date=dt.date(2022, 1, 1),  # must NEVER surface for as_of >= 2022
            )
        ],
    ),
    SeedDocument(
        key="retroactive_float",
        title="SECP SRO 88(I)/2026 — E-Money Float Income (Retrospective)",
        issuing_body="SECP",
        document_type="SRO",
        source_url="https://example-secp.gov.pk/sro/88-2026.pdf",
        published_date=dt.date(2026, 5, 30),
        chunks=[
            SeedChunk(
                legal_citation="Regulation 7(2)",
                heading_path="Part I > Regulation 7",
                content=(
                    "Interest or profit accrued on customer e-money float balances shall be "
                    "passed through to customers or applied to fee reduction; operators "
                    "shall not retain float income. This regulation takes effect "
                    "retrospectively from 1 January 2026."
                ),
                # valid-time (Jan) deliberately precedes ingestion (now) — the
                # retroactivity proof: ingested late, in force earlier.
                effective_date=dt.date(2026, 1, 1),
            )
        ],
    ),
    SeedDocument(
        key="unconfirmed_draft",
        title="SECP Draft Guidance — Merchant Settlement Cycles (UNDER REVIEW)",
        issuing_body="SECP",
        document_type="Notification",
        source_url="https://example-secp.gov.pk/drafts/merchant-cycles-2026.pdf",
        published_date=dt.date(2026, 4, 15),
        extraction_status=ExtractionStatus.REVIEW.value,
        review_reason="low_confidence",
        chunks=[
            SeedChunk(
                legal_citation="Para 1",
                heading_path="Draft Guidance > Para 1",
                content=(
                    "Draft guidance under review: proposed limits on merchant settlement "
                    "cycles for digital payment operators."
                ),
                effective_date=dt.date(2026, 5, 1),
            )
        ],
    ),
]

SEED_SUPERSESSIONS: list[SeedSupersession] = [
    SeedSupersession(
        superseded_doc_key="settlement_v1",
        superseding_doc_key="settlement_v2",
        relation=SupersessionRelation.AMENDS.value,
        effective_date=dt.date(2026, 6, 1),
    )
]
