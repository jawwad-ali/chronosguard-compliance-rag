"""Single import point for all table models.

Import order matters: ``base`` first (naming convention), then tables.
Alembic's env.py imports this module once — importing models anywhere else
re-uses these definitions, avoiding SQLModel duplicate-table errors.
"""

from chronosguard.models import base  # noqa: F401  (naming convention side effect)
from chronosguard.models.jobs import Job, JobKind, JobStatus
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
    "EffectiveDateSource",
    "ExtractionStatus",
    "Job",
    "JobKind",
    "JobStatus",
    "Jurisdiction",
    "Organization",
    "RegulatoryChunk",
    "RegulatoryDocument",
    "Supersession",
    "SupersessionRelation",
]
