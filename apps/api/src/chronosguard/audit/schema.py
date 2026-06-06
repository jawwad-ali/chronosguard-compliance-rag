"""The LLM verdict contract (strict Structured Outputs).

The model NEVER authors citations or URLs — it echoes a ``ref_id`` that maps
server-side to a DB chunk. Fabricated sources are structurally impossible.
"""

import enum

from pydantic import BaseModel, ConfigDict, Field


class Verdict(enum.StrEnum):
    VIOLATION = "VIOLATION"
    COMPLIANT = "COMPLIANT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class RiskLevel(enum.StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ClauseFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")  # strict mode requirement

    ref_id: str = Field(description="ref_id of the ONE excerpt this finding is grounded in")
    grounding_quote: str = Field(
        description="verbatim span copied exactly from that excerpt's content"
    )
    risk_level: RiskLevel
    rationale: str
    suggested_fix: str


class ClauseVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Verdict
    findings: list[ClauseFinding] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
