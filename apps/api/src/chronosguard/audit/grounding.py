"""Quote-grounding verification — the hard gate against hallucinated findings.

A finding whose ``grounding_quote`` does not occur in its cited excerpt is
DROPPED, and the clause downgrades to INSUFFICIENT_EVIDENCE if nothing valid
remains. The drop rate is the hallucination canary metric.
"""

import re

_WS_RE = re.compile(r"\s+")


_STRIP_CHARS = "\"'\u201c\u201d\u2018\u2019.\u2026"  # quotes, smart quotes, dots, ellipsis


def _normalize(text: str) -> str:
    return _WS_RE.sub(" ", text).strip().lower().strip(_STRIP_CHARS)


def quote_is_grounded(quote: str, content: str) -> bool:
    normalized_quote = _normalize(quote)
    if not normalized_quote:
        return False
    return normalized_quote in _normalize(content)
