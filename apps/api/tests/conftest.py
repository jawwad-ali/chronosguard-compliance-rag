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
                "VALUES ('PocketPay', 'PK'), ('Acme Corp', 'PK') RETURNING id"
            )
        )
        org_a, org_b = (row[0] for row in result.fetchall())

    yield org_a, org_b

    async with owner_engine.begin() as conn:
        await conn.execute(text("TRUNCATE organizations CASCADE"))
