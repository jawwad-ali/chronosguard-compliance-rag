"""audit_runs: ENABLE (not FORCE) RLS — owner is the maintenance channel.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-06

The staleness flagger (supersession confirm) must mark audit_runs across ALL
tenants — a deliberate cross-tenant maintenance write, operator-initiated,
running as cg_owner. FORCE RLS binds even the table owner, which would make
that flagger silently update zero rows. ENABLE keeps cg_app/cg_worker fully
bound (they are not owners) while cg_owner — never a runtime credential —
retains the maintenance channel, exactly like organizations provisioning.
audit_findings keeps FORCE: nothing legitimate ever writes it cross-tenant.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE audit_runs NO FORCE ROW LEVEL SECURITY;")


def downgrade() -> None:
    op.execute("ALTER TABLE audit_runs FORCE ROW LEVEL SECURITY;")
