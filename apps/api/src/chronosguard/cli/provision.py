"""Provisioning operations (owner role — bypasses RLS by design)."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from chronosguard.core.config import get_settings
from chronosguard.core.security import generate_api_key
from chronosguard.core.tenancy import effective_scopes


def _owner_engine() -> AsyncEngine:
    return create_async_engine(
        get_settings().database_url_owner,
        poolclass=NullPool,
        connect_args={"statement_cache_size": 0},
    )


async def create_jurisdiction(*, code: str, name: str) -> bool:
    engine = _owner_engine()
    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO jurisdictions (code, name) VALUES (:code, :name) "
                    "ON CONFLICT (code) DO NOTHING"
                ),
                {"code": code, "name": name},
            )
            return result.rowcount == 1
    finally:
        await engine.dispose()


async def create_organization(*, name: str, home_jurisdiction: str) -> int:
    engine = _owner_engine()
    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO organizations (name, home_jurisdiction) "
                    "VALUES (:name, :jur) RETURNING id"
                ),
                {"name": name, "jur": home_jurisdiction},
            )
            return int(result.scalar_one())
    finally:
        await engine.dispose()


async def create_api_key(*, org_id: int, name: str, scopes: list[str]) -> str:
    if not effective_scopes(scopes):
        msg = f"No valid scopes in {scopes!r} (valid: read, audit, admin)"
        raise ValueError(msg)

    settings = get_settings()
    generated = generate_api_key(settings.env)
    engine = _owner_engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO api_keys (tenant_id, prefix, key_hash, name, scopes) "
                    "VALUES (:tid, :prefix, :hash, :name, :scopes)"
                ),
                {
                    "tid": org_id,
                    "prefix": generated.prefix,
                    "hash": generated.key_hash,
                    "name": name,
                    "scopes": scopes,
                },
            )
    finally:
        await engine.dispose()
    return generated.full_key
