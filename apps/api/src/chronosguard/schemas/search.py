"""Regulatory search API shapes."""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from chronosguard.schemas.regulatory import ChunkOut


class RegulatorySearchRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "query": "How long may we hold customer funds before clearing?",
                "jurisdiction": "PK",
                "as_of_date": "2026-06-06",
                "top_k": 8,
            }
        }
    )

    query: str = Field(min_length=3, max_length=2000)
    jurisdiction: str = Field(min_length=2, max_length=16)
    as_of_date: dt.date | None = None  # default: today (UTC)
    top_k: int = Field(default=8, ge=1, le=25)


class ChunkHit(ChunkOut):
    score: float | None  # cosine similarity (1 - distance); None for citation-exact hits
    weak_match: bool
    source: Literal["vector", "citation"]


class RegulatorySearchResponse(BaseModel):
    jurisdiction: str
    as_of_date: dt.date
    items: list[ChunkHit]
