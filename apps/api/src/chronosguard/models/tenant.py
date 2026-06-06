"""Tenant root + auth principals.

``organizations`` is RLS-protected (policy: ``id = app_current_tenant()``).
``api_keys`` is deliberately NOT RLS-protected: it is the auth bootstrap table —
key lookup must work before any tenant context exists. It stores only hashes.
"""

import datetime as dt

from sqlalchemy import BigInteger
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.types import Text
from sqlmodel import Field, SQLModel

from chronosguard.models.base import bigint_pk, created_at_field, tztimestamp_field


class Organization(SQLModel, table=True):
    """The tenant root — ``tenant_id`` everywhere else equals ``organizations.id``."""

    __tablename__ = "organizations"

    id: int | None = bigint_pk()
    name: str = Field(unique=True)
    home_jurisdiction: str = Field(foreign_key="jurisdictions.code", max_length=16)
    created_at: dt.datetime | None = created_at_field()
    deleted_at: dt.datetime | None = tztimestamp_field()


class ApiKey(SQLModel, table=True):
    """Org-scoped machine credential: ``cgk_{env}_{prefix8}.{secret32}``.

    Stored: indexed plaintext prefix (O(1) lookup) + SHA-256(full_key + pepper).
    The plaintext secret is shown once at issuance and never persisted.
    """

    __tablename__ = "api_keys"

    id: int | None = bigint_pk()
    tenant_id: int = Field(foreign_key="organizations.id", index=True, sa_type=BigInteger)
    prefix: str = Field(unique=True, index=True, max_length=32)
    key_hash: str = Field(max_length=64)
    name: str
    scopes: list[str] = Field(sa_type=ARRAY(Text()))  # type: ignore[call-overload]
    created_at: dt.datetime | None = created_at_field()
    last_used_at: dt.datetime | None = tztimestamp_field()
    revoked_at: dt.datetime | None = tztimestamp_field()
    expires_at: dt.datetime | None = tztimestamp_field()
