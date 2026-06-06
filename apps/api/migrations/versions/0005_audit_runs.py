"""Audit runs + findings: tenant-scoped, RLS-FORCEd, append-only evidence.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-06

Grants encode the execution model: cg_app creates runs (INSERT) and reads;
cg_worker transitions runs (UPDATE) and writes findings — both under per-job
tenant context, both RLS-bound. DELETE exists for nobody: this is the
evidence record.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("policy_id", sa.BigInteger(), nullable=True),
        sa.Column("policy_version_id", sa.BigInteger(), nullable=True),
        sa.Column("policy_text_snapshot", sa.String(), nullable=False),
        sa.Column(
            "clauses_snapshot", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("jurisdiction", sa.String(length=16), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("verdict", sa.String(length=32), nullable=True),
        sa.Column("coverage", JSONB(), nullable=True),
        sa.Column("stale", sa.Boolean(), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column(
            "retrieved_chunk_ids",
            JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_audit_runs"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["organizations.id"], name="fk_audit_runs_tenant_id_organizations"
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"], ["org_policies.id"], name="fk_audit_runs_policy_id_org_policies"
        ),
        sa.ForeignKeyConstraint(
            ["policy_version_id"],
            ["org_policy_versions.id"],
            name="fk_audit_runs_policy_version_id_org_policy_versions",
        ),
        sa.ForeignKeyConstraint(
            ["jurisdiction"],
            ["jurisdictions.code"],
            name="fk_audit_runs_jurisdiction_jurisdictions",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'partial', 'failed')",
            name="ck_audit_runs_status_valid",
        ),
        sa.CheckConstraint(
            "verdict IS NULL OR verdict IN "
            "('COMPLIANT', 'VIOLATIONS_FOUND', 'INSUFFICIENT_EVIDENCE')",
            name="ck_audit_runs_verdict_valid",
        ),
    )
    op.create_index("ix_audit_runs_tenant_id", "audit_runs", ["tenant_id"])
    op.create_index("ix_audit_runs_status", "audit_runs", ["status"])
    op.execute(
        """
        CREATE TRIGGER trg_audit_runs_updated_at
        BEFORE UPDATE ON audit_runs
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    op.create_table(
        "audit_findings",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("clause_index", sa.Integer(), nullable=False),
        sa.Column("offending_policy_text", sa.String(), nullable=False),
        sa.Column("legal_rule_text", sa.String(), nullable=False),
        sa.Column("citation", sa.String(), nullable=False),
        sa.Column("source_chunk_id", sa.BigInteger(), nullable=True),
        sa.Column("source_document_id", sa.BigInteger(), nullable=True),
        sa.Column("source_url", sa.String(), nullable=False),
        sa.Column("risk_level", sa.String(length=8), nullable=False),
        sa.Column("grounding_quote", sa.String(), nullable=False),
        sa.Column("rationale", sa.String(), nullable=False),
        sa.Column("suggested_fix", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_findings"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["organizations.id"], name="fk_audit_findings_tenant_id_organizations"
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["audit_runs.id"], name="fk_audit_findings_run_id_audit_runs"
        ),
        sa.ForeignKeyConstraint(
            ["source_chunk_id"],
            ["regulatory_chunks.id"],
            name="fk_audit_findings_source_chunk_id_regulatory_chunks",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["regulatory_documents.id"],
            name="fk_audit_findings_source_document_id_regulatory_documents",
        ),
        sa.CheckConstraint(
            "risk_level IN ('HIGH', 'MEDIUM', 'LOW')", name="ck_audit_findings_risk_level_valid"
        ),
    )
    op.create_index("ix_audit_findings_tenant_id", "audit_findings", ["tenant_id"])
    op.create_index("ix_audit_findings_run_id", "audit_findings", ["run_id"])

    for table in ("audit_runs", "audit_findings"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
                FOR ALL TO cg_app, cg_worker
                USING (tenant_id = app_current_tenant())
                WITH CHECK (tenant_id = app_current_tenant());
            """
        )

    op.execute("GRANT SELECT, INSERT ON audit_runs TO cg_app;")
    op.execute("GRANT SELECT ON audit_findings TO cg_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE ON audit_runs TO cg_worker;")
    op.execute("GRANT SELECT, INSERT ON audit_findings TO cg_worker;")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_runs_updated_at ON audit_runs;")
    op.drop_table("audit_findings")
    op.drop_table("audit_runs")
