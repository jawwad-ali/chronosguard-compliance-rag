"""Tenant policy documents (RLS-enforced).

``org_policies`` is the logical document (mutable title, soft-delete,
current-version pointer). ``org_policy_versions`` is immutable text — every
body change appends a version; audits reference a version, so findings stay
explainable after later edits.
"""

import datetime as dt

from sqlalchemy import BigInteger, UniqueConstraint
from sqlmodel import Field, SQLModel

from chronosguard.models.base import (
    bigint_pk,
    created_at_field,
    tztimestamp_field,
    updated_at_field,
)


class OrgPolicy(SQLModel, table=True):
    __tablename__ = "org_policies"

    id: int | None = bigint_pk()
    tenant_id: int = Field(foreign_key="organizations.id", index=True, sa_type=BigInteger)
    title: str = Field(max_length=300)
    current_version_no: int = Field(default=1)
    created_at: dt.datetime | None = created_at_field()
    updated_at: dt.datetime | None = updated_at_field()
    deleted_at: dt.datetime | None = tztimestamp_field()


class OrgPolicyVersion(SQLModel, table=True):
    __tablename__ = "org_policy_versions"
    __table_args__ = (UniqueConstraint("policy_id", "version_no"),)

    id: int | None = bigint_pk()
    tenant_id: int = Field(foreign_key="organizations.id", index=True, sa_type=BigInteger)
    policy_id: int = Field(foreign_key="org_policies.id", index=True, sa_type=BigInteger)
    version_no: int
    body: str  # confidential — never logged in full (redaction processor)
    created_at: dt.datetime | None = created_at_field()
