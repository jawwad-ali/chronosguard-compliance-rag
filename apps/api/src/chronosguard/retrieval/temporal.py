"""THE canonical temporal predicate — the product's load-bearing correctness.

There is exactly ONE implementation of "what law was in force in jurisdiction
J on date D" in this codebase, and this is it. Audit retrieval, the regulatory
search endpoint, and the eval harness all import from here. A second
implementation anywhere is a rejected PR (docs/ROADMAP.md working agreement #1).

Rules encoded:
1. Half-open validity interval: ``effective_date <= d < expiration_date``
   (NULL expiration = open-ended). Dates, not timestamps — legal effectivity
   is a calendar concept.
2. Review gate: chunks of unconfirmed documents NEVER surface
   (extraction_status must be 'confirmed').
3. Embedding gate: a chunk without an embedding is not yet retrievable.
"""

import datetime as dt

from sqlalchemy import ColumnElement, and_, or_
from sqlmodel import col, select
from sqlmodel.sql.expression import SelectOfScalar

from chronosguard.models import ExtractionStatus, RegulatoryChunk, RegulatoryDocument


def as_of_predicate(jurisdiction: str, as_of: dt.date) -> ColumnElement[bool]:
    """In-force filter. Requires regulatory_documents to be joined."""
    return and_(
        col(RegulatoryChunk.jurisdiction) == jurisdiction,
        col(RegulatoryChunk.effective_date) <= as_of,
        or_(
            col(RegulatoryChunk.expiration_date).is_(None),
            col(RegulatoryChunk.expiration_date) > as_of,
        ),
        col(RegulatoryChunk.embedding).is_not(None),
        col(RegulatoryDocument.extraction_status) == ExtractionStatus.CONFIRMED.value,
    )


def in_force_chunks(jurisdiction: str, as_of: dt.date) -> SelectOfScalar[RegulatoryChunk]:
    """SELECT of chunks in force — the join is baked in so it can't be forgotten."""
    return (
        select(RegulatoryChunk)
        .join(
            RegulatoryDocument,
            col(RegulatoryChunk.document_id) == col(RegulatoryDocument.id),
        )
        .where(as_of_predicate(jurisdiction, as_of))
    )


def resolve_as_of(target_date: dt.date | None) -> dt.date:
    """API rule: missing as-of anchors to today (UTC calendar date)."""
    return target_date or dt.datetime.now(dt.UTC).date()
