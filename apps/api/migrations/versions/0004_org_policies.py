"""Tenant policies: org_policies + immutable org_policy_versions, RLS-enforced.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-06

FORCE RLS here (unlike organizations): tenant_id is an explicit column the
writer supplies, so WITH CHECK works for INSERTs — even the table owner is
bound. Versions are immutable: no UPDATE grant exists for anyone at runtime.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = ("org_policies", "org_policy_versions")


def upgrade() -> None:
    op.create_table(
        "org_policies",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("current_version_no", sa.Integer(), nullable=False),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_org_policies"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["organizations.id"], name="fk_org_policies_tenant_id_organizations"
        ),
    )
    op.create_index("ix_org_policies_tenant_id", "org_policies", ["tenant_id"])
    op.execute(
        """
        CREATE TRIGGER trg_org_policies_updated_at
        BEFORE UPDATE ON org_policies
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    op.create_table(
        "org_policy_versions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("policy_id", sa.BigInteger(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("body", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_org_policy_versions"),
        sa.UniqueConstraint("policy_id", "version_no", name="uq_org_policy_versions_policy_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name="fk_org_policy_versions_tenant_id_organizations",
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["org_policies.id"],
            name="fk_org_policy_versions_policy_id_org_policies",
        ),
    )
    op.create_index("ix_org_policy_versions_tenant_id", "org_policy_versions", ["tenant_id"])
    op.create_index("ix_org_policy_versions_policy_id", "org_policy_versions", ["policy_id"])

    for table in TENANT_TABLES:
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

    # cg_app: CRUD minus DELETE (retirement is a soft-delete UPDATE).
    # Versions are immutable: INSERT + SELECT only, for everyone.
    op.execute("GRANT SELECT, INSERT, UPDATE ON org_policies TO cg_app;")
    op.execute("GRANT SELECT, INSERT ON org_policy_versions TO cg_app;")
    # The audit worker reads policy text per job (under per-job tenant context).
    op.execute("GRANT SELECT ON org_policies, org_policy_versions TO cg_worker;")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_org_policies_updated_at ON org_policies;")
    op.drop_table("org_policy_versions")
    op.drop_table("org_policies")
