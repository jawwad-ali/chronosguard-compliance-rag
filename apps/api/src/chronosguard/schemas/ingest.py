"""Admin ingestion API shapes — the n8n contract.

The body carries HINTS only. Callers can never supply legal temporal fields
(effective/expiration dates, supersession links): those are derived by
extraction + provenance + the review gate, or the gate is meaningless.
"""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class IngestRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "source_url": "https://www.secp.gov.pk/circulars/circular-12-2026.pdf",
                "title": "SECP Circular No. 12 of 2026",
                "issuing_body": "SECP",
                "document_type": "Circular",
                "jurisdiction": "PK",
                "published_date": "2026-06-01",
            }
        }
    )

    source_url: HttpUrl
    title: str = Field(min_length=3, max_length=300)
    issuing_body: str = Field(min_length=2, max_length=64)
    document_type: str = Field(min_length=2, max_length=32)
    jurisdiction: str = Field(min_length=2, max_length=16)
    published_date: dt.date
    source_etag: str | None = None  # latency hint only


class IngestJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: Literal["ingest", "audit"]
    status: Literal["queued", "running", "succeeded", "failed"]
    ref_id: int | None  # document id once ingested
    attempts: int
    error: str | None
    created_at: dt.datetime
    updated_at: dt.datetime
