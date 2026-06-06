"""Model foundations: naming convention + shared field factories.

IMPORTANT: this module must be imported before ANY table class is defined so
the naming convention applies to every constraint — ``models/__init__.py``
enforces the order. Deterministic constraint names keep migrations reversible.
"""

import datetime as dt
from typing import Any

from sqlalchemy import BigInteger, Column, Identity, text
from sqlalchemy.types import DateTime
from sqlmodel import Field, SQLModel

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

SQLModel.metadata.naming_convention = NAMING_CONVENTION


def bigint_pk() -> Any:
    """BIGINT GENERATED ALWAYS AS IDENTITY primary key (fresh Column per model)."""
    return Field(
        default=None,
        sa_column=Column(BigInteger, Identity(always=True), primary_key=True),
    )


def created_at_field() -> Any:
    """Server-defaulted TIMESTAMPTZ — the DB clock is the authority, never the app's."""
    return Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
        sa_column_kwargs={"server_default": text("now()"), "nullable": False},
    )


def updated_at_field() -> Any:
    """Maintained by the ``set_updated_at`` trigger (migration 0001)."""
    return Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
        sa_column_kwargs={"server_default": text("now()"), "nullable": False},
    )


def tztimestamp_field(*, nullable: bool = True) -> Any:
    """Plain TIMESTAMPTZ column without defaults."""
    return Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
        sa_column_kwargs={"nullable": nullable},
    )


UTC = dt.UTC
