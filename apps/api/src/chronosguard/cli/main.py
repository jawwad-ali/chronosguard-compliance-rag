"""``chronos`` — operator CLI.

Provisioning commands (jurisdictions, orgs, keys) are owner-role operations:
they bypass RLS deliberately and never run inside the API process.
"""

import asyncio
from collections.abc import Awaitable, Callable

import typer

from chronosguard.cli.provision import (
    create_api_key,
    create_jurisdiction,
    create_organization,
)
from chronosguard.cli.seed import seed_with_default_engine

app = typer.Typer(help="ChronosGuard operator CLI", no_args_is_help=True)
jurisdictions_app = typer.Typer(help="Manage jurisdiction codes", no_args_is_help=True)
org_app = typer.Typer(help="Manage organizations (tenants)", no_args_is_help=True)
keys_app = typer.Typer(help="Manage org API keys", no_args_is_help=True)
app.add_typer(jurisdictions_app, name="jurisdictions")
app.add_typer(org_app, name="org")
app.add_typer(keys_app, name="keys")


def _run[T](coro: Awaitable[T]) -> T:
    return asyncio.run(_as_coro(coro))


async def _as_coro[T](awaitable: Awaitable[T]) -> T:
    return await awaitable


@jurisdictions_app.command("add")
def jurisdictions_add(code: str, name: str) -> None:
    """Register a jurisdiction code (e.g. PK 'Pakistan')."""
    created = _run(create_jurisdiction(code=code.upper(), name=name))
    typer.echo(f"{'Created' if created else 'Already exists'}: {code.upper()}")


@org_app.command("create")
def org_create(
    name: str,
    jurisdiction: str = typer.Option("PK", "--jurisdiction", "-j"),
) -> None:
    """Provision a tenant organization."""
    org_id = _run(create_organization(name=name, home_jurisdiction=jurisdiction.upper()))
    typer.echo(f"Created organization id={org_id} name={name!r}")


@keys_app.command("create")
def keys_create(
    org_id: int = typer.Option(..., "--org-id"),
    name: str = typer.Option("default", "--name"),
    scopes: str = typer.Option("read", "--scopes", help="Comma-separated: read,audit,admin"),
) -> None:
    """Issue an API key. The full key is printed ONCE and never stored."""
    scope_list = [scope.strip() for scope in scopes.split(",") if scope.strip()]
    full_key = _run(create_api_key(org_id=org_id, name=name, scopes=scope_list))
    typer.echo("API key created. Store it now — it cannot be recovered:")
    typer.echo(full_key)


@app.command("seed")
def seed() -> None:
    """Load the development corpus (idempotent; fake embeddings, zero spend)."""
    inserted = _run(seed_with_default_engine())
    typer.echo(f"Seed complete: {inserted} new document(s).")


def main() -> None:
    app()


# Re-export for [project.scripts]
run: Callable[[], None] = main
