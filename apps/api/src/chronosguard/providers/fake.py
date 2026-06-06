"""Deterministic fake providers — CI never spends OpenAI money.

FakeEmbeddings: token-hash bag-of-words vectors; shared vocabulary ⇒ genuinely
higher cosine similarity, so ranking tests are meaningful and free.

FakeChat: a rule-based auditor over the structured prompt payload — compares
"N business days" limits between clause and excerpts; scriptable per-test.
"""

import hashlib
import json
import math
import re
from collections.abc import Callable
from typing import Any, cast

from pydantic import BaseModel

from chronosguard.audit.schema import ClauseFinding, ClauseVerdict, RiskLevel, Verdict
from chronosguard.models import EMBEDDING_DIMS
from chronosguard.providers.base import TokenUsage

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _vectorize(text: str, dims: int) -> list[float]:
    vector = [0.0] * dims
    for token in _TOKEN_RE.findall(text.lower()):
        digest = hashlib.sha256(token.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % dims
        vector[index] += 1.0
    norm = math.sqrt(sum(component * component for component in vector))
    if norm == 0.0:
        vector[0] = 1.0
        return vector
    return [component / norm for component in vector]


class FakeEmbeddings:
    model = "fake-token-hash-v1"
    dims = EMBEDDING_DIMS

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [_vectorize(text, self.dims) for text in texts]


_DAYS_LIMIT_RE = re.compile(r"(?:\((\d+)\)|(\d+))\s+business days", re.IGNORECASE)
_MIN_OVERLAP_FOR_COMPLIANT = 5


def _days_limit(text: str) -> int | None:
    match = _DAYS_LIMIT_RE.search(text)
    if match is None:
        return None
    return int(match.group(1) or match.group(2))


def _sentence_with(content: str, needle: str) -> str:
    for sentence in re.split(r"(?<=[.!?])\s+", content):
        if needle.lower() in sentence.lower():
            return sentence.strip()
    return content.strip()


def _token_overlap(a: str, b: str) -> int:
    return len(set(_TOKEN_RE.findall(a.lower())) & set(_TOKEN_RE.findall(b.lower())))


def _heuristic_verdict(payload: dict[str, Any]) -> ClauseVerdict:
    clause: str = payload["policy_clause"]
    clause_days = _days_limit(clause)
    for excerpt in payload.get("excerpts", []):
        excerpt_days = _days_limit(excerpt["content"])
        if clause_days is not None and excerpt_days is not None and clause_days > excerpt_days:
            return ClauseVerdict(
                verdict=Verdict.VIOLATION,
                findings=[
                    ClauseFinding(
                        ref_id=excerpt["ref_id"],
                        grounding_quote=_sentence_with(excerpt["content"], "business days"),
                        risk_level=RiskLevel.HIGH,
                        rationale=(
                            f"Policy allows {clause_days} business days but the rule "
                            f"permits at most {excerpt_days}."
                        ),
                        suggested_fix=(
                            f"Reduce the holding window to {excerpt_days} business days."
                        ),
                    )
                ],
                confidence=0.95,
            )
    if any(
        _token_overlap(clause, excerpt["content"]) >= _MIN_OVERLAP_FOR_COMPLIANT
        for excerpt in payload.get("excerpts", [])
    ):
        return ClauseVerdict(verdict=Verdict.COMPLIANT, findings=[], confidence=0.8)
    return ClauseVerdict(verdict=Verdict.INSUFFICIENT_EVIDENCE, findings=[], confidence=0.5)


class FakeChat:
    """Deterministic auditor. ``script`` overrides the heuristic per test."""

    model = "fake-chat-v1"

    def __init__(self, script: Callable[[dict[str, Any]], ClauseVerdict] | None = None) -> None:
        self._script = script

    async def complete_structured[T: BaseModel](
        self, *, system: str, user: str, response_model: type[T]
    ) -> tuple[T, TokenUsage]:
        payload = json.loads(user)
        verdict = self._script(payload) if self._script else _heuristic_verdict(payload)
        usage = TokenUsage(prompt_tokens=len(user) // 4, completion_tokens=64)
        return cast("T", verdict), usage
