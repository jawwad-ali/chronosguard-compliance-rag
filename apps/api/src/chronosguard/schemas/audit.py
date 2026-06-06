"""Audit API shapes — 202 + poll; verdict is tri-state, never a bare boolean."""

import datetime as dt
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from chronosguard.schemas.policy import MAX_POLICY_BODY_CHARS

RunStatusLiteral = Literal["queued", "running", "succeeded", "partial", "failed"]
VerdictLiteral = Literal["COMPLIANT", "VIOLATIONS_FOUND", "INSUFFICIENT_EVIDENCE"]


class AuditCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"policy_id": 1, "jurisdiction": "PK", "as_of_date": "2026-06-06"}
        }
    )

    policy_id: int | None = None
    policy_text: str | None = Field(default=None, min_length=1, max_length=MAX_POLICY_BODY_CHARS)
    jurisdiction: str = Field(min_length=2, max_length=16)
    as_of_date: dt.date | None = None  # temporal anchor; default = today (UTC)

    @model_validator(mode="after")
    def _exactly_one_source(self) -> Self:
        if (self.policy_id is None) == (self.policy_text is None):
            msg = "Provide exactly one of: policy_id, policy_text"
            raise ValueError(msg)
        return self


class Coverage(BaseModel):
    violation: int = 0
    compliant: int = 0
    insufficient_evidence: int = 0
    error: int = 0


class AuditRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: RunStatusLiteral
    verdict: VerdictLiteral | None
    coverage: Coverage | None
    stale: bool
    jurisdiction: str
    as_of_date: dt.date
    policy_id: int | None
    policy_version_id: int | None
    model: str | None
    total_tokens: int
    cost_usd: float | None
    error: str | None
    created_at: dt.datetime
    finished_at: dt.datetime | None


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    clause_index: int
    risk_level: Literal["HIGH", "MEDIUM", "LOW"]
    offending_policy_text: str
    legal_rule_text: str
    citation: str
    grounding_quote: str
    rationale: str
    suggested_fix: str
    source_chunk_id: int | None
    source_document_id: int | None
    source_url: str
    confidence: float
    needs_review: bool
