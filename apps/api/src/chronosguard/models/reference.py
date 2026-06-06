"""Global reference tables (no RLS, read-only to runtime roles)."""

from sqlmodel import Field, SQLModel


class Jurisdiction(SQLModel, table=True):
    """Validated jurisdiction codes, optionally nested (PK > PK-SINDH)."""

    __tablename__ = "jurisdictions"

    code: str = Field(primary_key=True, max_length=16)  # "PK", "US-TX", "EU"
    name: str
    parent_code: str | None = Field(default=None, foreign_key="jurisdictions.code")
