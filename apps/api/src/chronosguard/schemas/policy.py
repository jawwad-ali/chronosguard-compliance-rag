"""Tenant policy API shapes."""

import datetime as dt
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_POLICY_BODY_CHARS = 200_000


class PolicyCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=MAX_POLICY_BODY_CHARS)


class PolicyUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    body: str | None = Field(default=None, min_length=1, max_length=MAX_POLICY_BODY_CHARS)

    @model_validator(mode="after")
    def _require_something(self) -> Self:
        if self.title is None and self.body is None:
            msg = "Provide at least one of: title, body"
            raise ValueError(msg)
        return self


class PolicySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    current_version_no: int
    created_at: dt.datetime
    updated_at: dt.datetime


class PolicyOut(PolicySummary):
    body: str  # current version text


class PolicyVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version_no: int
    body: str
    created_at: dt.datetime
