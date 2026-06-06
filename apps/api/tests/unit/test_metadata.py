"""Rule-based metadata extraction: dates, provenance, supersession refs."""

import datetime as dt

from chronosguard.ingestion.metadata import extract_metadata
from tests.chunkers_fixture import STRUCTURED_GAZETTE

PUBLISHED = dt.date(2026, 8, 15)


class TestEffectiveDate:
    def test_extracts_come_into_force_date(self) -> None:
        meta = extract_metadata(STRUCTURED_GAZETTE, published_date=PUBLISHED)
        assert meta.effective_date == dt.date(2026, 9, 1)
        assert meta.effective_date_source == "extracted"
        assert meta.effective_date_evidence is not None
        assert meta.effective_date_evidence in STRUCTURED_GAZETTE  # anti-fabrication

    def test_wef_abbreviation(self) -> None:
        meta = extract_metadata(
            "These rules apply w.e.f. 15th March, 2026 to all banks.",
            published_date=PUBLISHED,
        )
        assert meta.effective_date == dt.date(2026, 3, 15)
        assert meta.effective_date_source == "extracted"

    def test_iso_date_format(self) -> None:
        meta = extract_metadata(
            "This directive takes effect from 2026-04-01 onward.", published_date=PUBLISHED
        )
        assert meta.effective_date == dt.date(2026, 4, 1)

    def test_immediate_effect_defaults_to_published_with_provenance(self) -> None:
        meta = extract_metadata(
            "This circular applies with immediate effect.", published_date=PUBLISHED
        )
        assert meta.effective_date == PUBLISHED
        assert meta.effective_date_source == "defaulted_to_published"
        assert meta.effective_date_evidence == "with immediate effect"

    def test_dateless_document_defaults_honestly(self) -> None:
        meta = extract_metadata("General guidance on record keeping.", published_date=PUBLISHED)
        assert meta.effective_date == PUBLISHED
        assert meta.effective_date_source == "defaulted_to_published"
        assert meta.effective_date_evidence is None


class TestSupersedesRefs:
    def test_extracts_superseded_circular_reference(self) -> None:
        meta = extract_metadata(STRUCTURED_GAZETTE, published_date=PUBLISHED)
        assert any("Circular No. 5 of 2019" in ref for ref in meta.supersedes_refs)

    def test_no_refs_when_absent(self) -> None:
        meta = extract_metadata("Plain guidance text.", published_date=PUBLISHED)
        assert meta.supersedes_refs == []
