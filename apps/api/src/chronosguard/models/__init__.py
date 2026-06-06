"""Single import point for all table models.

Import order matters: ``base`` first (naming convention), then tables.
Alembic's env.py imports this module once — importing models anywhere else
re-uses these definitions, avoiding SQLModel duplicate-table errors.
"""

from chronosguard.models import base  # noqa: F401  (naming convention side effect)
from chronosguard.models.audit import AuditFinding, AuditRun, RunStatus, RunVerdict
from chronosguard.models.jobs import Job, JobKind, JobStatus
from chronosguard.models.policy import OrgPolicy, OrgPolicyVersion
from chronosguard.models.reference import Jurisdiction
from chronosguard.models.regulatory import (
    EMBEDDING_DIMS,
    EffectiveDateSource,
    ExtractionStatus,
    RegulatoryChunk,
    RegulatoryDocument,
    Supersession,
    SupersessionRelation,
)
from chronosguard.models.tenant import ApiKey, Organization

__all__ = [
    "EMBEDDING_DIMS",
    "ApiKey",
    "AuditFinding",
    "AuditRun",
    "EffectiveDateSource",
    "ExtractionStatus",
    "Job",
    "JobKind",
    "JobStatus",
    "Jurisdiction",
    "OrgPolicy",
    "OrgPolicyVersion",
    "Organization",
    "RegulatoryChunk",
    "RegulatoryDocument",
    "RunStatus",
    "RunVerdict",
    "Supersession",
    "SupersessionRelation",
]
