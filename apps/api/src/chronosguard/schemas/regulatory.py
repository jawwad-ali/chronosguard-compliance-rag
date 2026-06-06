"""Regulatory corpus API shapes (read-only to tenants)."""

import datetime as dt

from pydantic import BaseModel, ConfigDict


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    issuing_body: str
    document_type: str
    jurisdiction: str
    language: str
    version: int
    published_date: dt.date


class DocumentDetail(DocumentSummary):
    source_url: str
    ingested_at: dt.datetime
    chunk_count: int


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    chunk_index: int
    legal_citation: str
    heading_path: str
    content: str
    jurisdiction: str
    effective_date: dt.date
    effective_date_source: str
    expiration_date: dt.date | None
