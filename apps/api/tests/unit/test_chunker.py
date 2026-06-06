"""Hierarchical chunker: structure detection, breadcrumbs, bounds, fallback."""

from chronosguard.ingestion.chunker import MAX_CHUNK_CHARS, chunk_document
from tests.chunkers_fixture import STRUCTURED_GAZETTE


class TestStructuredChunking:
    def test_detects_part_and_regulation_hierarchy(self) -> None:
        result = chunk_document(STRUCTURED_GAZETTE, doc_title="Test Circular")
        assert not result.used_fallback
        paths = [chunk.heading_path for chunk in result.chunks]
        assert any("PART I" in path and "Regulation 1" in path for path in paths)
        assert any("PART II" in path and "Regulation 3" in path for path in paths)

    def test_breadcrumb_prefixes_embed_text(self) -> None:
        result = chunk_document(STRUCTURED_GAZETTE, doc_title="Test Circular")
        for chunk in result.chunks:
            assert chunk.embed_text.startswith(f"[{chunk.heading_path}]")
            assert chunk.text in chunk.embed_text

    def test_citation_is_leaf_heading(self) -> None:
        result = chunk_document(STRUCTURED_GAZETTE, doc_title="Test Circular")
        reg2 = next(c for c in result.chunks if "segregated safeguarding" in c.text)
        assert reg2.legal_citation.startswith("Regulation 2")

    def test_chunks_respect_max_bound(self) -> None:
        huge_section = "PART I\n\nRegulation 1 - Big\n" + ("word " * 2000)
        result = chunk_document(huge_section, doc_title="T")
        assert all(len(chunk.text) <= MAX_CHUNK_CHARS for chunk in result.chunks)

    def test_continuation_chunks_are_labeled(self) -> None:
        huge_section = (
            "PART I\n\nRegulation 1 - Big\n" + ("paragraph text here. " * 50 + "\n\n") * 8
        )
        result = chunk_document(huge_section, doc_title="T")
        if len(result.chunks) > 1:
            assert any("(cont." in chunk.heading_path for chunk in result.chunks[1:])


class TestFallback:
    def test_unstructured_text_uses_fallback_and_flags(self) -> None:
        text = "Just a few paragraphs of prose without legal structure. " * 30
        result = chunk_document(text, doc_title="Unstructured Notice")
        assert result.used_fallback  # MUST be flagged — silent fallback is forbidden
        assert all(chunk.heading_path.startswith("Unstructured Notice") for chunk in result.chunks)
        assert len(result.chunks) >= 1
