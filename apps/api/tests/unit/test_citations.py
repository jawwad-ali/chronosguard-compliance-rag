"""Citation extractor patterns."""

from chronosguard.retrieval.citations import extract_citations


class TestExtractCitations:
    def test_extracts_section_style(self) -> None:
        assert extract_citations("Per Section 12-B(4)(a) of the Act") == ["Section 12-B(4)(a)"]

    def test_extracts_regulation_and_para(self) -> None:
        found = extract_citations("Regulation 7(2) read with Para 4(a).")
        assert "Regulation 7(2)" in found
        assert "Para 4(a)" in found

    def test_extracts_circular_with_year(self) -> None:
        assert extract_citations("see Circular No. 7 of 2025") == ["Circular No. 7 of 2025"]

    def test_extracts_sro_reference(self) -> None:
        assert extract_citations("under SRO 1234(I)/2026") == ["SRO 1234(I)/2026"]

    def test_dedupes_preserving_order(self) -> None:
        text = "Rule 9 conflicts with Rule 9; also see Article 5."
        assert extract_citations(text) == ["Rule 9", "Article 5"]

    def test_no_citations_returns_empty(self) -> None:
        assert extract_citations("hold funds for seven business days") == []

    def test_normalizes_internal_whitespace(self) -> None:
        assert extract_citations("Section\t 41") == ["Section 41"]
