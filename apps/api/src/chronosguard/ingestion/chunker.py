"""Hierarchical legal chunker: structure-aware splitting, breadcrumb injection.

Heading detection targets SECP/SBP conventions (PART / CHAPTER / Section /
Regulation / numbered clauses). When fewer than two headings are found the
document falls back to fixed windows and is FLAGGED for review — the fallback
must never silently masquerade as structure (docs/ARCHITECTURE.md §6).
"""

import re
from dataclasses import dataclass

#: Token bounds approximated at ~4 chars/token (tiktoken deferred — MVP).
MIN_CHUNK_CHARS = 240  # ~60 tokens — merge smaller leaves forward
MAX_CHUNK_CHARS = 3_200  # ~800 tokens — split larger leaves on paragraphs
FALLBACK_WINDOW_CHARS = 2_400
FALLBACK_OVERLAP_CHARS = 320
MIN_HEADINGS_FOR_STRUCTURE = 2

_HEADING_PATTERNS: list[tuple[int, re.Pattern[str]]] = [
    (1, re.compile(r"^#{0,3}\s*PART\s+([IVXLC]+|\d+)\b.*$", re.IGNORECASE)),
    (2, re.compile(r"^#{0,3}\s*CHAPTER\s+([IVXLC]+|\d+)\b.*$", re.IGNORECASE)),
    (
        3,
        re.compile(
            r"^#{0,4}\s*(?:Section|Regulation|Rule|Article)\s+\d+[0-9A-Za-z\-]*\b.*$",
            re.IGNORECASE,
        ),
    ),
    (
        3,
        re.compile(r"^#{0,4}\s*(?:SRO|Circular|Notification)\s*(?:No\.?\s*)?\d+.*$", re.IGNORECASE),
    ),
    (4, re.compile(r"^\(?([a-z]|[ivx]{1,4}|\d{1,3})\)\s+\S.*$")),
]

_PARAGRAPH_RE = re.compile(r"\n\s*\n")


@dataclass(frozen=True)
class ChunkDraft:
    index: int
    heading_path: str
    legal_citation: str
    text: str  # raw clause text (stored as content)
    embed_text: str  # breadcrumb-prefixed text that gets embedded


@dataclass(frozen=True)
class ChunkingResult:
    chunks: list[ChunkDraft]
    used_fallback: bool  # True ⇒ flag the document for review


def _detect_heading(line: str) -> tuple[int, str] | None:
    stripped = line.strip()
    if not stripped:
        return None
    for level, pattern in _HEADING_PATTERNS:
        if pattern.match(stripped):
            return level, re.sub(r"^#{1,6}\s*", "", stripped)
    return None


def _wrap_on_spaces(text: str) -> list[str]:
    """Last-resort split for a single paragraph beyond the bound."""
    pieces: list[str] = []
    remaining = text
    while len(remaining) > MAX_CHUNK_CHARS:
        cut = remaining.rfind(" ", 0, MAX_CHUNK_CHARS)
        cut = cut if cut > 0 else MAX_CHUNK_CHARS
        pieces.append(remaining[:cut])
        remaining = remaining[cut:].lstrip()
    if remaining:
        pieces.append(remaining)
    return pieces


def _split_oversized(text: str) -> list[str]:
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]
    pieces: list[str] = []
    current = ""
    for paragraph in _PARAGRAPH_RE.split(text):
        if current and len(current) + len(paragraph) + 2 > MAX_CHUNK_CHARS:
            pieces.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}".strip()
    if current:
        pieces.append(current)
    return [wrapped for piece in pieces for wrapped in _wrap_on_spaces(piece)]


def _emit(sections: list[tuple[str, str]]) -> list[ChunkDraft]:
    """sections: (heading_path, body) pairs → bounded, breadcrumbed drafts."""
    merged: list[tuple[str, str]] = []
    for path, body in sections:
        text = body.strip()
        if not text:
            continue
        if merged and len(merged[-1][1]) < MIN_CHUNK_CHARS:
            # A runt (intro fragment, bare part-title) folds FORWARD into the
            # next substantial section — whose heading path wins.
            _, runt_body = merged.pop()
            text = f"{runt_body}\n\n{text}"
        merged.append((path, text))

    drafts: list[ChunkDraft] = []
    for path, body in merged:
        for piece_no, piece in enumerate(_split_oversized(body)):
            suffix = f" (cont. {piece_no})" if piece_no else ""
            citation = path.split(" > ")[-1] + suffix
            drafts.append(
                ChunkDraft(
                    index=len(drafts),
                    heading_path=path + suffix,
                    legal_citation=citation,
                    text=piece,
                    embed_text=f"[{path}{suffix}] {piece}",
                )
            )
    return drafts


def _structured_sections(lines: list[str], doc_title: str) -> tuple[list[tuple[str, str]], int]:
    stack: list[tuple[int, str]] = []  # (level, label)
    sections: list[tuple[str, str]] = []
    current_body: list[str] = []
    headings_found = 0

    def flush() -> None:
        path = " > ".join(label for _, label in stack) or doc_title
        sections.append((path, "\n".join(current_body)))
        current_body.clear()

    for line in lines:
        detected = _detect_heading(line)
        if detected is None:
            current_body.append(line)
            continue
        headings_found += 1
        flush()
        level, label = detected
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, label))
    flush()
    return sections, headings_found


def _fallback_windows(text: str, doc_title: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    start = 0
    while start < len(text):
        window = text[start : start + FALLBACK_WINDOW_CHARS]
        sections.append((doc_title, window))
        start += FALLBACK_WINDOW_CHARS - FALLBACK_OVERLAP_CHARS
    return sections


def chunk_document(markdown: str, *, doc_title: str) -> ChunkingResult:
    lines = markdown.splitlines()
    sections, headings_found = _structured_sections(lines, doc_title)

    if headings_found < MIN_HEADINGS_FOR_STRUCTURE:
        return ChunkingResult(
            chunks=_emit(_fallback_windows(markdown, doc_title)), used_fallback=True
        )
    return ChunkingResult(chunks=_emit(sections), used_fallback=False)
