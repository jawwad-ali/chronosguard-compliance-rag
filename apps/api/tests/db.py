"""Database test infrastructure (testcontainers pgvector + Alembic).

Imported lazily by fixtures so the unit lane never touches Docker.
The session fixture proves migration reversibility on every run:
upgrade head → downgrade base → upgrade head.
"""

import asyncio
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

PG_IMAGE = "pgvector/pgvector:pg16"
OWNER = ("cg_owner", "owner_test_pw")
APP = ("cg_app", "app_test_pw")
WORKER = ("cg_worker", "worker_test_pw")
DB_NAME = "chronosguard_test"


@dataclass(frozen=True)
class DatabaseInfo:
    owner_url: str
    app_url: str
    worker_url: str


def _url(user: str, password: str, host: str, port: int) -> str:
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{DB_NAME}"


async def _bootstrap_login_roles(owner_url: str) -> None:
    """Local-dev equivalent of infra/db-init: give runtime roles LOGIN."""
    engine = create_async_engine(owner_url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            for role, password in (APP, WORKER):
                await conn.execute(text(f"CREATE ROLE {role} LOGIN PASSWORD '{password}'"))
    finally:
        await engine.dispose()


def bootstrap_database(host: str, port: int) -> DatabaseInfo:
    """Create login roles, then run the full migration reversibility cycle."""
    from alembic import command
    from alembic.config import Config

    info = DatabaseInfo(
        owner_url=_url(*OWNER, host, port),
        app_url=_url(*APP, host, port),
        worker_url=_url(*WORKER, host, port),
    )
    asyncio.run(_bootstrap_login_roles(info.owner_url))

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", info.owner_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")  # reversibility is a gate, not an aspiration
    command.upgrade(cfg, "head")
    return info


def make_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, poolclass=NullPool, connect_args={"statement_cache_size": 0})


async def set_tenant_context(conn: AsyncConnection, tenant_id: int | str | None) -> None:
    """Transaction-local tenant context, exactly as the runtime sets it."""
    value = "" if tenant_id is None else str(tenant_id)
    await conn.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": value})
