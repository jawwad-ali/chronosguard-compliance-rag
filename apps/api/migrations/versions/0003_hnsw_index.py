"""HNSW index over chunk embeddings.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-06

One full HNSW index, cosine ops, partial on embedding IS NOT NULL (chunks
persist before their embeddings land — resumable ingestion). Per-jurisdiction
partial indexes and halfvec were cut in design review; their re-activation
triggers live in docs/ARCHITECTURE.md §11. This index is migration-only DDL
(exempted from the autogen drift gate by name in migrations/env.py).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX ix_chunks_embedding_hnsw
        ON regulatory_chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        WHERE embedding IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw;")
