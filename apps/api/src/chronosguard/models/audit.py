"""Audit runs + findings (tenant-scoped, RLS-enforced, append-only evidence).

A run snapshots everything it reasoned over (policy text, clause array,
retrieved chunk ids, as-of date) so findings stay explainable after the
corpus moves on. ``stale`` flips when a later retroactive amendment may
invalidate the stored verdict — verdicts never silently rot.
"""

import datetime as dt
import enum
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from chronosguard.models.base import (
    bigint_pk,
    created_at_field,
    tztimestamp_field,
    updated_at_field,
)


class RunStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"  # some clauses errored — verdict can never be COMPLIANT
    FAILED = "failed"


class RunVerdict(enum.StrEnum):
    COMPLIANT = "COMPLIANT"
    VIOLATIONS_FOUND = "VIOLATIONS_FOUND"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class AuditRun(SQLModel, table=True):
    __tablename__ = "audit_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'partial', 'failed')",
            name="status_valid",
        ),
        CheckConstraint(
            "verdict IS NULL OR verdict IN "
            "('COMPLIANT', 'VIOLATIONS_FOUND', 'INSUFFICIENT_EVIDENCE')",
            name="verdict_valid",
        ),
    )

    id: int | None = bigint_pk()
    tenant_id: int = Field(foreign_key="organizations.id", index=True, sa_type=BigInteger)
    policy_id: int | None = Field(default=None, foreign_key="org_policies.id", sa_type=BigInteger)
    policy_version_id: int | None = Field(
        default=None, foreign_key="org_policy_versions.id", sa_type=BigInteger
    )
    policy_text_snapshot: str  # confidential — redacted in logs
    clauses_snapshot: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_type=JSONB,
        sa_column_kwargs={"server_default": text("'[]'::jsonb"), "nullable": False},
    )
    jurisdiction: str = Field(foreign_key="jurisdictions.code", max_length=16)
    as_of_date: dt.date  # the temporal anchor — snapshotted, reproducible
    status: str = Field(default=RunStatus.QUEUED.value, max_length=16, index=True)
    verdict: str | None = Field(default=None, max_length=32)
    coverage: dict[str, Any] | None = Field(default=None, sa_type=JSONB)
    stale: bool = Field(default=False)
    model: str | None = Field(default=None, max_length=64)
    total_tokens: int = Field(default=0)
    cost_usd: float | None = None
    retrieved_chunk_ids: list[int] = Field(
        default_factory=list,
        sa_type=JSONB,
        sa_column_kwargs={"server_default": text("'[]'::jsonb"), "nullable": False},
    )
    error: str | None = None
    created_at: dt.datetime | None = created_at_field()
    updated_at: dt.datetime | None = updated_at_field()
    finished_at: dt.datetime | None = tztimestamp_field()


class AuditFinding(SQLModel, table=True):
    __tablename__ = "audit_findings"
    __table_args__ = (
        CheckConstraint("risk_level IN ('HIGH', 'MEDIUM', 'LOW')", name="risk_level_valid"),
    )

    id: int | None = bigint_pk()
    tenant_id: int = Field(foreign_key="organizations.id", index=True, sa_type=BigInteger)
    run_id: int = Field(foreign_key="audit_runs.id", index=True, sa_type=BigInteger)
    clause_index: int
    offending_policy_text: str
    legal_rule_text: str  # chunk content FROM THE DB — never LLM-authored
    citation: str  # from the DB
    source_chunk_id: int | None = Field(
        default=None, foreign_key="regulatory_chunks.id", sa_type=BigInteger
    )
    source_document_id: int | None = Field(
        default=None, foreign_key="regulatory_documents.id", sa_type=BigInteger
    )
    source_url: str  # from the DB
    risk_level: str = Field(max_length=8)
    grounding_quote: str  # verified verbatim span
    rationale: str
    suggested_fix: str
    confidence: float
    needs_review: bool = Field(default=False)  # weak retrieval or low confidence
    created_at: dt.datetime | None = created_at_field()
