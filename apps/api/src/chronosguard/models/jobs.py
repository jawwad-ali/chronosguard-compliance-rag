"""The single durable job queue (audit + ingest).

GLOBAL table (no RLS) by design: the worker must see queued jobs across all
tenants to claim them. ``tenant_id`` rides on the job row; the worker opens a
fresh transaction and sets tenant context per job before tenant-scoped work.
"""

import datetime as dt
import enum
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from chronosguard.models.base import (
    bigint_pk,
    created_at_field,
    tztimestamp_field,
    updated_at_field,
)


class JobKind(enum.StrEnum):
    AUDIT = "audit"
    INGEST = "ingest"


class JobStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Job(SQLModel, table=True):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("kind IN ('audit', 'ingest')", name="kind_valid"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')", name="status_valid"
        ),
        Index(
            "ix_jobs_claim",
            "status",
            "created_at",
            postgresql_where=text("status = 'queued'"),
        ),
    )

    id: int | None = bigint_pk()
    kind: str = Field(max_length=16)  # JobKind
    # audit_runs.id | regulatory_documents.id
    ref_id: int | None = Field(default=None, sa_type=BigInteger)
    tenant_id: int | None = Field(default=None, foreign_key="organizations.id", sa_type=BigInteger)
    status: str = Field(default=JobStatus.QUEUED.value, max_length=16, index=True)
    payload: dict[str, Any] = Field(
        default_factory=dict,
        sa_type=JSONB,
        sa_column_kwargs={"server_default": text("'{}'::jsonb"), "nullable": False},
    )
    attempts: int = Field(default=0)
    max_attempts: int = Field(default=3)
    error: str | None = None
    locked_at: dt.datetime | None = tztimestamp_field()
    locked_by: str | None = None
    created_at: dt.datetime | None = created_at_field()
    updated_at: dt.datetime | None = updated_at_field()
