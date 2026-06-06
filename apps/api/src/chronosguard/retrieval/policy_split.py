"""Deterministic policy clause splitter — the unit of audit is the clause.

No LLM involved: blank lines, markdown headings, and numbered/lettered list
items delimit clauses; runts merge into their predecessor; over-long clauses
hard-split on sentence boundaries. Deterministic ⇒ reproducible audits.
"""

import re
from dataclasses import dataclass

# Below ~40 chars a segment is a genuine fragment (a heading, a list stub) —
# real policy clauses are often single short sentences and must stand alone.
MIN_CLAUSE_CHARS = 40
MAX_CLAUSE_CHARS = 1_500

_BOUNDARY_RE = re.compile(
    r"\n\s*\n"  # blank line
    r"|\n(?=#{1,6}\s)"  # markdown heading
    r"|\n(?=\d+[.)]\s)"  # 1.  2)
    r"|\n(?=\([a-z0-9ivx]+\)\s)",  # (a) (i) (1)
    re.IGNORECASE,
)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class PolicyClause:
    index: int
    text: str


def _hard_split(segment: str) -> list[str]:
    if len(segment) <= MAX_CLAUSE_CHARS:
        return [segment]
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_RE.split(segment):
        if current and len(current) + len(sentence) + 1 > MAX_CLAUSE_CHARS:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def split_policy(text: str) -> list[PolicyClause]:
    raw_segments = [segment.strip() for segment in _BOUNDARY_RE.split(text) if segment.strip()]

    merged: list[str] = []
    for segment in raw_segments:
        if merged and len(merged[-1]) < MIN_CLAUSE_CHARS:
            merged[-1] = f"{merged[-1]}\n{segment}"
        else:
            merged.append(segment)

    bounded: list[str] = []
    for segment in merged:
        bounded.extend(_hard_split(segment))

    return [PolicyClause(index=i, text=segment) for i, segment in enumerate(bounded)]
