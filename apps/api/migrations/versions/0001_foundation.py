"""Foundation: extension, roles, reference + tenant + queue tables, RLS spine.

Revision ID: 0001
Revises:
Create Date: 2026-06-06

Security model (docs/ARCHITECTURE.md §3.5):
- cg_owner  — migrations only; owns all tables. NEVER a runtime credential.
- cg_app    — API request path. Not owner, no BYPASSRLS ⇒ RLS always binds it.
- cg_worker — background worker + ingestion CLI. RLS-bound on tenant tables.

Roles are created NOLOGIN if absent (cluster-level, idempotent); LOGIN +
passwords are environment bootstrap (infra/db-init locally, runbook on Neon) —
credentials never live in migrations.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNTIME_ROLES = ("cg_app", "cg_worker")


def _create_roles() -> None:
    for role in RUNTIME_ROLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
                    CREATE ROLE {role} NOLOGIN;
                END IF;
            END
            $$;
            """
        )


def _create_functions() -> None:
    # THE tenant-context reader. NULLIF guard: unset AND empty-string both yield
    # NULL -> RLS predicate UNKNOWN -> zero rows. Fail-closed by construction.
    op.execute(
        """
        CREATE FUNCTION app_current_tenant() RETURNS bigint
        LANGUAGE sql STABLE
        AS $$
            SELECT NULLIF(current_setting('app.tenant_id', true), '')::bigint
        $$;
        """
    )
    op.execute(
        """
        CREATE FUNCTION set_updated_at() RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            -- clock_timestamp(), not now(): now() is frozen per-transaction,
            -- so claim-then-update within one txn would never advance it.
            NEW.updated_at := clock_timestamp();
            RETURN NEW;
        END;
        $$;
        """
    )


def _create_tables() -> None:
    op.create_table(
        "jurisdictions",
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("parent_code", sa.String(length=16), nullable=True),
        sa.PrimaryKeyConstraint("code", name="pk_jurisdictions"),
        sa.ForeignKeyConstraint(
            ["parent_code"],
            ["jurisdictions.code"],
            name="fk_jurisdictions_parent_code_jurisdictions",
        ),
    )

    op.create_table(
        "organizations",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("home_jurisdiction", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_organizations"),
        sa.UniqueConstraint("name", name="uq_organizations_name"),
        sa.ForeignKeyConstraint(
            ["home_jurisdiction"],
            ["jurisdictions.code"],
            name="fk_organizations_home_jurisdiction_jurisdictions",
        ),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("prefix", sa.String(length=32), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("scopes", ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_api_keys"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["organizations.id"], name="fk_api_keys_tenant_id_organizations"
        ),
    )
    op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"])
    op.create_index("ix_api_keys_prefix", "api_keys", ["prefix"], unique=True)

    op.create_table(
        "jobs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("ref_id", sa.BigInteger(), nullable=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("payload", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["organizations.id"], name="fk_jobs_tenant_id_organizations"
        ),
        sa.CheckConstraint("kind IN ('audit', 'ingest')", name="ck_jobs_kind_valid"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_jobs_status_valid"
        ),
    )
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index(
        "ix_jobs_claim",
        "jobs",
        ["status", "created_at"],
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.execute(
        """
        CREATE TRIGGER trg_jobs_updated_at
        BEFORE UPDATE ON jobs
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def _create_rls() -> None:
    # organizations: ENABLE (deliberately not FORCE). The tenant key IS the
    # generated id, so a WITH CHECK insert policy can never pass — provisioning
    # runs as cg_owner (table owner, bypasses non-forced RLS). cg_app/cg_worker
    # are not owners ⇒ fully bound. Roles without a policy get default-deny.
    op.execute("ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON organizations
            FOR ALL TO cg_app, cg_worker
            USING (id = app_current_tenant())
            WITH CHECK (id = app_current_tenant());
        """
    )
    # api_keys: NO RLS — auth bootstrap table (lookup precedes tenant context).
    # jobs: NO RLS — global queue; the worker claims across tenants by design.


def _create_grants() -> None:
    op.execute("GRANT SELECT ON jurisdictions TO cg_app, cg_worker;")
    op.execute("GRANT SELECT ON organizations TO cg_app, cg_worker;")
    op.execute("GRANT SELECT ON api_keys TO cg_app;")
    op.execute("GRANT UPDATE (last_used_at) ON api_keys TO cg_app;")
    op.execute("GRANT SELECT, INSERT ON jobs TO cg_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON jobs TO cg_worker;")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    _create_roles()
    _create_functions()
    _create_tables()
    _create_rls()
    _create_grants()


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_jobs_updated_at ON jobs;")
    op.drop_table("jobs")
    op.drop_table("api_keys")
    op.drop_table("organizations")
    op.drop_table("jurisdictions")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at();")
    op.execute("DROP FUNCTION IF EXISTS app_current_tenant();")
    # Roles are cluster-level and intentionally survive downgrade (idempotent
    # creation guards re-upgrade); the extension may be shared — leave it.
