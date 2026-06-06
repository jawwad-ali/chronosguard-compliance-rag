"""Rule-based metadata extraction with honest provenance.

Deliberately NOT LLM-driven at MVP (right-sizing call): legal effectivity
phrases in SECP/SBP documents are regular enough for patterns, results are
fully deterministic and testable, and ingestion gains no OpenAI dependency.
The seam stays: swap in an LLM-assisted extractor behind the same signature
when real-corpus data shows the patterns failing (deferred register).

Convention (docs/ARCHITECTURE.md §6): "with immediate effect" and date-less
documents anchor to the PUBLICATION date with explicit
``effective_date_source = defaulted_to_published`` provenance — honest,
queryable, surfaced to findings as needs-review context.
"""

import datetime as dt
import re
from dataclasses import dataclass, field

from chronosguard.models import EffectiveDateSource

_MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
#: "1 July 2026", "1st July, 2026", "July 1, 2026", "2026-07-01"
_DATE_PATTERNS = [
    re.compile(
        rf"(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<month>{_MONTHS})[,\s]+(?P<year>\d{{4}})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?P<month>{_MONTHS})\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?[,\s]+(?P<year>\d{{4}})",
        re.IGNORECASE,
    ),
    re.compile(r"(?P<year>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})"),
]

_EFFECTIVE_CONTEXT_RE = re.compile(
    r"(?:with effect from|w\.?\s?e\.?\s?f\.?|effective from|shall come into force on|"
    r"comes? into force on|takes? effect(?: retrospectively)? from)\s+(?P<rest>[^.\n]{0,60})",
    re.IGNORECASE,
)
_IMMEDIATE_EFFECT_RE = re.compile(r"with immediate effect", re.IGNORECASE)

_SUPERSEDES_RE = re.compile(
    r"(?:supersedes?|repeals?|replaces?|in supersession of)\s+"
    r"(?P<ref>(?:Circular|SRO|Notification)\s*(?:No\.?\s*)?[\d()IVX/\-]+(?:\s+of\s+\d{4})?)",
    re.IGNORECASE,
)

_MONTH_INDEX = {name: i + 1 for i, name in enumerate(_MONTHS.split("|"))}


@dataclass(frozen=True)
class ExtractedMetadata:
    effective_date: dt.date
    effective_date_source: str
    effective_date_evidence: str | None
    supersedes_refs: list[str] = field(default_factory=list)


def _parse_date(text: str) -> dt.date | None:
    for pattern in _DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        groups = match.groupdict()
        try:
            if "month" in groups and groups.get("month"):
                return dt.date(
                    int(groups["year"]),
                    _MONTH_INDEX[groups["month"].lower()],
                    int(groups["day"]),
                )
            return dt.date(int(groups["year"]), int(groups["m"]), int(groups["d"]))
        except (ValueError, KeyError):
            continue
    return None


def extract_metadata(markdown: str, *, published_date: dt.date) -> ExtractedMetadata:
    supersedes = [
        re.sub(r"\s+", " ", match.group("ref").strip())
        for match in _SUPERSEDES_RE.finditer(markdown)
    ]

    for match in _EFFECTIVE_CONTEXT_RE.finditer(markdown):
        parsed = _parse_date(match.group("rest"))
        if parsed is not None:
            evidence = match.group(0).strip()
            # Anti-fabrication invariant: evidence must literally occur in source.
            if evidence in markdown:
                return ExtractedMetadata(
                    effective_date=parsed,
                    effective_date_source=EffectiveDateSource.EXTRACTED.value,
                    effective_date_evidence=evidence,
                    supersedes_refs=supersedes,
                )

    # "with immediate effect" or no commencement clause at all: anchor to
    # publication, with provenance saying exactly that.
    evidence_text = None
    immediate = _IMMEDIATE_EFFECT_RE.search(markdown)
    if immediate:
        evidence_text = immediate.group(0)
    return ExtractedMetadata(
        effective_date=published_date,
        effective_date_source=EffectiveDateSource.DEFAULTED_TO_PUBLISHED.value,
        effective_date_evidence=evidence_text,
        supersedes_refs=supersedes,
    )
