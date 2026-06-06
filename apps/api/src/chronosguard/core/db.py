"""Async engines + session management.

Two runtime engines, two roles (docs/ARCHITECTURE.md §3.5):
- request path  → ``cg_app``    (least privilege, RLS-bound)
- worker / CLI  → ``cg_worker`` (corpus writes + per-job tenant context)

``statement_cache_size=0`` keeps asyncpg safe behind any transaction pooler;
``pool_pre_ping`` + recycle absorb Neon idle-suspend.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from chronosguard.core.config import get_settings


def build_engine(url: str, *, pool_size: int, max_overflow: int, recycle: int) -> AsyncEngine:
    return create_async_engine(
        url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,
        pool_recycle=recycle,
        connect_args={"statement_cache_size": 0},
    )


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return build_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        recycle=settings.db_pool_recycle_seconds,
    )


@lru_cache
def get_worker_engine() -> AsyncEngine:
    settings = get_settings()
    return build_engine(
        settings.database_url_worker,
        pool_size=2,
        max_overflow=2,
        recycle=settings.db_pool_recycle_seconds,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False, autoflush=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session, one transaction, per request.

    Commit on clean handler return; rollback on any exception. The transaction
    boundary IS the tenancy boundary — ``SET LOCAL app.tenant_id`` (set by the
    auth dependency) lives and dies with this transaction.
    """
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def make_db_readiness_check(engine: AsyncEngine) -> Callable[[], Awaitable[bool]]:
    async def check_database() -> bool:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True

    return check_database


async def dispose_engines() -> None:
    for factory in (get_engine, get_worker_engine):
        if factory.cache_info().currsize:
            await factory().dispose()
    get_engine.cache_clear()
    get_worker_engine.cache_clear()
    get_sessionmaker.cache_clear()
