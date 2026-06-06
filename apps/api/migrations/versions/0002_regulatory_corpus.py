"""Regulatory corpus: documents, chunks (vector-ready), supersession lineage.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-06

Global tables — no RLS (shared corpus). cg_app reads; cg_worker writes
(ingestion). DELETE is granted to nobody: the corpus is never deleted, only
temporally retired via expiration_date. The HNSW index lands in 0003 (built
after the first bulk load — post-load builds are far faster).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIMS = 1536


def upgrade() -> None:
    op.create_table(
        "regulatory_documents",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("issuing_body", sa.String(), nullable=False),
        sa.Column("document_type", sa.String(), nullable=False),
        sa.Column("jurisdiction", sa.String(length=16), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("source_url", sa.String(), nullable=False),
        sa.Column("source_etag", sa.String(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("published_date", sa.Date(), nullable=False),
        sa.Column("extraction_status", sa.String(length=16), nullable=False),
        sa.Column("review_reason", sa.String(), nullable=True),
        sa.Column("raw_markdown", sa.String(), nullable=True),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_regulatory_documents"),
        sa.UniqueConstraint(
            "source_url", "content_hash", name="uq_regulatory_documents_source_url"
        ),
        sa.ForeignKeyConstraint(
            ["jurisdiction"],
            ["jurisdictions.code"],
            name="fk_regulatory_documents_jurisdiction_jurisdictions",
        ),
        sa.CheckConstraint(
            "extraction_status IN ('pending', 'review', 'confirmed')",
            name="ck_regulatory_documents_extraction_status_valid",
        ),
    )
    op.create_index("ix_regulatory_documents_title", "regulatory_documents", ["title"])
    op.create_index(
        "ix_regulatory_documents_issuing_body", "regulatory_documents", ["issuing_body"]
    )
    op.create_index(
        "ix_regulatory_documents_document_type", "regulatory_documents", ["document_type"]
    )
    op.create_index(
        "ix_regulatory_documents_jurisdiction", "regulatory_documents", ["jurisdiction"]
    )

    op.create_table(
        "regulatory_chunks",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("embed_text_hash", sa.String(length=64), nullable=False),
        sa.Column("legal_citation", sa.String(), nullable=False),
        sa.Column("heading_path", sa.String(), nullable=False),
        sa.Column("jurisdiction", sa.String(length=16), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("effective_date_source", sa.String(length=32), nullable=False),
        sa.Column("expiration_date", sa.Date(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("embedding_model", sa.String(length=64), nullable=False),
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIMS), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_regulatory_chunks"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["regulatory_documents.id"],
            name="fk_regulatory_chunks_document_id_regulatory_documents",
        ),
        sa.ForeignKeyConstraint(
            ["jurisdiction"],
            ["jurisdictions.code"],
            name="fk_regulatory_chunks_jurisdiction_jurisdictions",
        ),
        sa.CheckConstraint(
            "effective_date_source IN ('extracted', 'defaulted_to_published', "
            "'operator_confirmed')",
            name="ck_regulatory_chunks_effective_date_source_valid",
        ),
        sa.CheckConstraint(
            "expiration_date IS NULL OR expiration_date > effective_date",
            name="ck_regulatory_chunks_interval_valid",
        ),
    )
    op.create_index("ix_regulatory_chunks_document_id", "regulatory_chunks", ["document_id"])
    op.create_index("ix_regulatory_chunks_jurisdiction", "regulatory_chunks", ["jurisdiction"])
    op.create_index("ix_regulatory_chunks_effective_date", "regulatory_chunks", ["effective_date"])
    op.create_index(
        "ix_regulatory_chunks_expiration_date", "regulatory_chunks", ["expiration_date"]
    )
    op.create_index(
        "ix_chunks_jur_temporal",
        "regulatory_chunks",
        ["jurisdiction", "effective_date", "expiration_date"],
    )

    op.create_table(
        "supersessions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("superseded_chunk_id", sa.BigInteger(), nullable=False),
        sa.Column("superseding_chunk_id", sa.BigInteger(), nullable=True),
        sa.Column("relation", sa.String(length=16), nullable=False),
        sa.Column("supersession_effective_date", sa.Date(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_supersessions"),
        sa.ForeignKeyConstraint(
            ["superseded_chunk_id"],
            ["regulatory_chunks.id"],
            name="fk_supersessions_superseded_chunk_id_regulatory_chunks",
        ),
        sa.ForeignKeyConstraint(
            ["superseding_chunk_id"],
            ["regulatory_chunks.id"],
            name="fk_supersessions_superseding_chunk_id_regulatory_chunks",
        ),
        sa.CheckConstraint(
            "relation IN ('amends', 'repeals', 'replaces')",
            name="ck_supersessions_relation_valid",
        ),
    )
    op.create_index(
        "ix_supersessions_superseded_chunk_id", "supersessions", ["superseded_chunk_id"]
    )

    # Grants: corpus is read-only to the API role; the worker ingests.
    op.execute("GRANT SELECT ON regulatory_documents, regulatory_chunks, supersessions TO cg_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE ON regulatory_documents TO cg_worker;")
    op.execute("GRANT SELECT, INSERT, UPDATE ON regulatory_chunks TO cg_worker;")
    op.execute("GRANT SELECT, INSERT ON supersessions TO cg_worker;")


def downgrade() -> None:
    op.drop_table("supersessions")
    op.drop_table("regulatory_chunks")
    op.drop_table("regulatory_documents")
