"""Deterministic legal-citation extraction.

Legal text has exact-match needs vectors can miss ("Section 12-B", "Circular
No. 7 of 2025"). The extractor feeds an exact lookup merged into vector
candidates. Full FTS+RRF is DEFERRED behind this same seam.
"""

import re

_CITATION_PATTERNS = [
    # Section 12-B(4)(a) / Sec. 41 / Regulation 7(2) / Rule 9 / Para 4(a) / Article 5
    re.compile(
        r"\b(?:Section|Sec\.?|Regulation|Reg\.?|Rule|Para(?:graph)?|Article|Clause)\s+"
        r"\d+[0-9A-Za-z\-()]*",
        re.IGNORECASE,
    ),
    # Circular No. 7 of 2025 / SRO 1234(I)/2026 / Notification 88 of 2026
    re.compile(
        r"\b(?:Circular|SRO|Notification)\s+(?:No\.?\s*)?\d+[0-9A-Za-z\-()/]*"
        r"(?:\s+of\s+\d{4})?",
        re.IGNORECASE,
    ),
]


def extract_citations(text: str) -> list[str]:
    """Unique citation mentions, original order, whitespace-normalized."""
    seen: dict[str, None] = {}
    for pattern in _CITATION_PATTERNS:
        for match in pattern.finditer(text):
            normalized = re.sub(r"\s+", " ", match.group(0).strip())
            seen.setdefault(normalized, None)
    return list(seen)
