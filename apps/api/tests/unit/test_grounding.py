"""Quote-grounding gate."""

from chronosguard.audit.grounding import quote_is_grounded

CONTENT = (
    "All retail digital payment accounts must settle transit funds within a strict "
    "maximum window of three (3) business days. Holding customer funds beyond "
    "seventy-two (72) hours requires prior written approval."
)


class TestQuoteGrounding:
    def test_exact_quote_passes(self) -> None:
        assert quote_is_grounded("three (3) business days", CONTENT)

    def test_whitespace_and_case_variation_passes(self) -> None:
        assert quote_is_grounded("  THREE (3)   Business Days ", CONTENT)

    def test_surrounding_quotemarks_stripped(self) -> None:
        assert quote_is_grounded('"three (3) business days."', CONTENT)

    def test_fabricated_quote_fails(self) -> None:
        assert not quote_is_grounded("funds must be settled instantly", CONTENT)

    def test_paraphrase_fails(self) -> None:
        assert not quote_is_grounded("settle funds in 3 days max", CONTENT)

    def test_empty_quote_fails(self) -> None:
        assert not quote_is_grounded("", CONTENT)
        assert not quote_is_grounded('"”', CONTENT)
