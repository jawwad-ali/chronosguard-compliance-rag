"""``chronos`` — operator CLI.

Provisioning (jurisdictions, orgs, keys) and corpus maintenance (confirm,
supersede) are owner-role operations: they bypass RLS deliberately and never
run inside the API process. Ingestion runs under the worker role.
"""

import asyncio
import datetime as dt
import json
from collections.abc import Awaitable, Callable
from pathlib import Path

import typer

from chronosguard.cli import ingest_ops
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
ingest_app = typer.Typer(help="Ingest regulatory documents", no_args_is_help=True)
worker_app = typer.Typer(help="Run the job worker", no_args_is_help=True)
app.add_typer(jurisdictions_app, name="jurisdictions")
app.add_typer(org_app, name="org")
app.add_typer(keys_app, name="keys")
app.add_typer(ingest_app, name="ingest")
app.add_typer(worker_app, name="worker")


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


@ingest_app.command("url")
def ingest_url(
    source_url: str,
    title: str = typer.Option(..., "--title"),
    issuing_body: str = typer.Option(..., "--body"),
    document_type: str = typer.Option("Circular", "--type"),
    jurisdiction: str = typer.Option("PK", "--jurisdiction", "-j"),
    published: str = typer.Option(..., "--published", help="YYYY-MM-DD"),
) -> None:
    """Enqueue ingestion of a regulatory document by URL."""
    job_id = _run(
        ingest_ops.enqueue_ingest(
            source_url=source_url,
            file_path=None,
            title=title,
            issuing_body=issuing_body,
            document_type=document_type,
            jurisdiction=jurisdiction.upper(),
            published_date=dt.date.fromisoformat(published),
        )
    )
    typer.echo(f"Queued ingest job {job_id}. Run `chronos worker run-once` to process.")


@ingest_app.command("file")
def ingest_file(
    path: Path,
    title: str = typer.Option(..., "--title"),
    issuing_body: str = typer.Option(..., "--body"),
    document_type: str = typer.Option("Circular", "--type"),
    jurisdiction: str = typer.Option("PK", "--jurisdiction", "-j"),
    published: str = typer.Option(..., "--published", help="YYYY-MM-DD"),
) -> None:
    """Enqueue ingestion of a local .pdf or .md file."""
    job_id = _run(
        ingest_ops.enqueue_ingest(
            source_url=f"file://{path.resolve().as_posix()}",
            file_path=str(path.resolve()),
            title=title,
            issuing_body=issuing_body,
            document_type=document_type,
            jurisdiction=jurisdiction.upper(),
            published_date=dt.date.fromisoformat(published),
        )
    )
    typer.echo(f"Queued ingest job {job_id}. Run `chronos worker run-once` to process.")


@worker_app.command("run-once")
def worker_run_once(max_jobs: int = typer.Option(None, "--max-jobs")) -> None:
    """Reap expired leases, then drain the queue (PaaS-cron friendly)."""
    processed = _run(ingest_ops.run_worker_once(max_jobs=max_jobs))
    typer.echo(f"Processed {processed} job(s).")


@app.command("status")
def status(
    review: bool = typer.Option(False, "--review", help="List documents awaiting review"),
    failed: bool = typer.Option(False, "--failed", help="List failed jobs"),
) -> None:
    """Queue + review-gate visibility."""
    if review:
        docs = _run(ingest_ops.list_review_documents())
        if not docs:
            typer.echo("Review queue is empty.")
        for doc_id, title, reason in docs:
            typer.echo(f"[{doc_id}] ({reason}) {title}")
        return
    jobs = _run(ingest_ops.list_jobs(status="failed" if failed else None))
    if not jobs:
        typer.echo("No jobs.")
    for job in jobs:
        error = f" error={job.error}" if job.error else ""
        typer.echo(f"[{job.id}] {job.kind} {job.status} attempts={job.attempts}{error}")


@app.command("confirm")
def confirm_doc(document_id: int) -> None:
    """Clear a review-quarantined document into retrieval (operator judgment)."""
    _run(ingest_ops.confirm(document_id))
    typer.echo(f"Document {document_id} confirmed — now retrievable.")


@app.command("supersede")
def supersede_doc(
    new_document_id: int,
    supersedes: int = typer.Option(..., "--supersedes", help="The OLD document id"),
    relation: str = typer.Option("amends", "--relation", help="amends|repeals|replaces"),
) -> None:
    """Close the old document's validity intervals + record lineage + flag stale runs."""
    report = _run(
        ingest_ops.supersede(
            new_document_id=new_document_id, old_document_id=supersedes, relation=relation
        )
    )
    typer.echo(
        f"Superseded {report.superseded_chunks} chunk(s) effective "
        f"{report.supersession_effective_date}; {report.stale_runs_flagged} past audit "
        f"run(s) flagged stale."
    )


@app.command("backfill-embeddings")
def backfill_embeddings() -> None:
    """Embed every chunk still missing a vector (crash-resume path)."""
    embedded = _run(ingest_ops.backfill_embeddings())
    typer.echo(f"Embedded {embedded} chunk(s).")


@app.command("retry")
def retry(job_id: int) -> None:
    """Re-queue a failed job."""
    if _run(ingest_ops.retry_job(job_id)):
        typer.echo(f"Job {job_id} re-queued.")
    else:
        typer.echo(f"Job {job_id} is not in a failed state.", err=True)
        raise typer.Exit(code=1)


_OPENAPI_OUTPUT_ARG = typer.Argument(Path("../../packages/contracts/openapi.json"))


@app.command("export-openapi")
def export_openapi(output: Path = _OPENAPI_OUTPUT_ARG) -> None:
    """Export the OpenAPI schema — the frozen contract for the UI and n8n."""
    from chronosguard.core.config import Settings  # noqa: PLC0415 — keep CLI startup light
    from chronosguard.main import create_app  # noqa: PLC0415

    schema = create_app(Settings(worker_enabled=False, log_level="WARNING")).openapi()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    typer.echo(f"OpenAPI schema written to {output}")


def main() -> None:
    app()


# Re-export for [project.scripts]
run: Callable[[], None] = main
