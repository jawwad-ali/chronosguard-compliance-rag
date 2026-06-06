"""Shared test fixtures.

Async tests run on anyio's asyncio backend; mark modules with
``pytestmark = pytest.mark.anyio``. Database fixtures import their heavy
dependencies lazily so the unit lane never touches Docker.
"""

from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from chronosguard.core.config import Settings
from chronosguard.main import create_app

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from tests.db import DatabaseInfo


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def settings() -> Settings:
    return Settings(env="local", log_level="WARNING")


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


# ── Database lane (integration / rls) ───────────────────────────────────────


@pytest.fixture(scope="session")
def database() -> "Iterator[DatabaseInfo]":
    """pgvector container with migrations applied (and proven reversible)."""
    from testcontainers.postgres import PostgresContainer

    from tests.db import DB_NAME, OWNER, PG_IMAGE, bootstrap_database

    user, password = OWNER
    with PostgresContainer(PG_IMAGE, username=user, password=password, dbname=DB_NAME) as pg:
        host = pg.get_container_host_ip()
        port = int(pg.get_exposed_port(5432))
        yield bootstrap_database(host, port)


@pytest.fixture
async def owner_engine(database: "DatabaseInfo") -> "AsyncIterator[AsyncEngine]":
    from tests.db import make_engine

    engine = make_engine(database.owner_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def app_engine(database: "DatabaseInfo") -> "AsyncIterator[AsyncEngine]":
    """Engine connected as cg_app — the ONLY honest way to test RLS."""
    from tests.db import make_engine

    engine = make_engine(database.app_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def worker_engine(database: "DatabaseInfo") -> "AsyncIterator[AsyncEngine]":
    from tests.db import make_engine

    engine = make_engine(database.worker_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def two_orgs(owner_engine: "AsyncEngine") -> "AsyncIterator[tuple[int, int]]":
    """Two seeded tenants; all tenant data truncated afterwards."""
    from sqlalchemy import text

    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO jurisdictions (code, name) VALUES ('PK', 'Pakistan') "
                "ON CONFLICT (code) DO NOTHING"
            )
        )
        result = await conn.execute(
            text(
                "INSERT INTO organizations (name, home_jurisdiction) "
                "VALUES ('PocketPay', 'PK'), ('Acme Corp', 'PK') "
                "ON CONFLICT (name) DO NOTHING RETURNING id"
            )
        )
        ids = [row[0] for row in result.fetchall()]
        if len(ids) < 2:  # pre-existing (e.g. seed corpus ran first) — look up
            rows = await conn.execute(
                text(
                    "SELECT id FROM organizations "
                    "WHERE name IN ('PocketPay', 'Acme Corp') ORDER BY id"
                )
            )
            ids = [row[0] for row in rows.fetchall()]
        org_a, org_b = ids[0], ids[1]

    yield org_a, org_b

    async with owner_engine.begin() as conn:
        await conn.execute(text("TRUNCATE organizations CASCADE"))


@pytest.fixture
async def seeded_corpus(owner_engine: "AsyncEngine") -> None:
    """Idempotent seed of the six-document temporal fixture corpus."""
    from chronosguard.cli.seed import seed_corpus

    await seed_corpus(owner_engine)


@pytest.fixture
def api_app(app_engine: "AsyncEngine") -> FastAPI:
    """The real app wired to the test DB AS cg_app — requests exercise real RLS."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from chronosguard.core.db import get_session

    application = create_app(Settings(log_level="WARNING"))
    maker = async_sessionmaker(app_engine, expire_on_commit=False, autoflush=False)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    application.dependency_overrides[get_session] = override_session
    return application


@pytest.fixture
async def api(api_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=api_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


async def issue_key(
    owner_engine: "AsyncEngine", org_id: int, scopes: list[str], *, revoked: bool = False
) -> str:
    """Insert an API key for a test org; returns the full plaintext key."""
    from sqlalchemy import text

    from chronosguard.core.security import generate_api_key

    generated = generate_api_key("local")  # default pepper — same one the app verifies with
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO api_keys (tenant_id, prefix, key_hash, name, scopes, revoked_at) "
                "VALUES (:tid, :prefix, :hash, 'test', :scopes, "
                "CASE WHEN :revoked THEN now() ELSE NULL END)"
            ),
            {
                "tid": org_id,
                "prefix": generated.prefix,
                "hash": generated.key_hash,
                "scopes": scopes,
                "revoked": revoked,
            },
        )
    return generated.full_key
