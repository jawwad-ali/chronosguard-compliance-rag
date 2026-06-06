"""PDF → Markdown extraction + safety heuristics.

``pymupdf4llm``: pure-Python wheels, fast, Markdown headings/tables/reading
order — right for digital-native gazettes. Scanned PDFs are REJECTED to the
review queue (no OCR in MVP); non-English-primary documents likewise — the
explicit Pakistan-market scoping decision: never silently mis-ingest Urdu
(docs/ARCHITECTURE.md §10). Both heuristics are pure functions, unit-tested.
"""

import asyncio
import re
from dataclasses import dataclass

import pymupdf
import pymupdf4llm  # type: ignore[import-untyped]

#: Below this many extractable chars/page the PDF is image-dominant (scanned).
MIN_CHARS_PER_PAGE = 100
#: Above this share of Arabic-script chars the document is not English-primary.
MAX_ARABIC_SCRIPT_RATIO = 0.15

_ARABIC_BLOCK_RE = re.compile("[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
_INJECTION_PATTERN_RE = re.compile(
    r"ignore (?:all |any )?(?:previous|prior) instructions|system prompt|you are now",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ExtractedDoc:
    markdown: str
    page_count: int
    chars_per_page: float


def is_scanned(extracted: ExtractedDoc) -> bool:
    return extracted.chars_per_page < MIN_CHARS_PER_PAGE


def arabic_script_ratio(text: str) -> float:
    if not text:
        return 0.0
    return len(_ARABIC_BLOCK_RE.findall(text)) / len(text)


def is_non_english_primary(text: str) -> bool:
    return arabic_script_ratio(text) > MAX_ARABIC_SCRIPT_RATIO


def has_injection_patterns(text: str) -> bool:
    """Instruction-like content in a gazette is quarantined, not just flagged."""
    return _INJECTION_PATTERN_RE.search(text) is not None


def _extract_sync(pdf_bytes: bytes) -> ExtractedDoc:
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
        page_count = doc.page_count or 1
        total_chars = sum(len(page.get_text()) for page in doc)
        markdown = pymupdf4llm.to_markdown(doc)
    return ExtractedDoc(
        markdown=markdown,
        page_count=page_count,
        chars_per_page=total_chars / page_count,
    )


async def extract_markdown(pdf_bytes: bytes) -> ExtractedDoc:
    """CPU-bound parse off the event loop."""
    return await asyncio.to_thread(_extract_sync, pdf_bytes)
