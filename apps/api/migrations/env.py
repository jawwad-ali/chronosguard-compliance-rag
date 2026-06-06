"""Alembic environment — async engine, SQLModel metadata, owner-role connection.

URL precedence: ``alembic.ini sqlalchemy.url`` (set programmatically by tests)
→ ``Settings.database_url_owner`` (reads .env / process env). Migrations always
run as ``cg_owner``; runtime roles never perform DDL.
"""

import asyncio

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

import chronosguard.models  # noqa: F401  — populate SQLModel.metadata (single import point)
from chronosguard.core.config import get_settings

config = context.config
target_metadata = SQLModel.metadata


def _database_url() -> str:
    configured = config.get_main_option("sqlalchemy.url")
    if configured:
        return configured
    return get_settings().database_url_owner


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_database_url(), connect_args={"statement_cache_size": 0})
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
