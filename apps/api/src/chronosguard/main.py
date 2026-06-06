"""Application factory."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from chronosguard import __version__
from chronosguard.api.health import readiness_checks
from chronosguard.api.health import router as health_router
from chronosguard.api.v1 import v1_router
from chronosguard.core.config import Settings, get_settings
from chronosguard.core.db import (
    dispose_engines,
    get_engine,
    get_worker_engine,
    make_db_readiness_check,
)
from chronosguard.core.errors import register_exception_handlers
from chronosguard.core.logging import setup_logging
from chronosguard.core.middleware import RequestContextMiddleware
from chronosguard.core.sentry import setup_sentry
from chronosguard.providers import get_chat_provider, get_embedding_provider
from chronosguard.worker.runner import Worker

#: API pool + overflow + worker pool + overflow (core/db.py) + CLI headroom.
_WORKER_POOL_CONNECTIONS = 4
_CLI_HEADROOM_CONNECTIONS = 4


def _assert_connection_budget(settings: Settings) -> None:
    planned = (
        settings.db_pool_size
        + settings.db_max_overflow
        + _WORKER_POOL_CONNECTIONS
        + _CLI_HEADROOM_CONNECTIONS
    )
    if planned > settings.db_connection_budget:
        msg = (
            f"Connection plan ({planned}) exceeds DB_CONNECTION_BUDGET "
            f"({settings.db_connection_budget}) — lower pool sizes or raise the budget "
            "to match the Neon tier ceiling."
        )
        raise ValueError(msg)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    _assert_connection_budget(settings)
    readiness_checks["database"] = make_db_readiness_check(get_engine())

    worker_task: asyncio.Task[None] | None = None
    stop = asyncio.Event()
    if settings.worker_enabled:
        worker = Worker(
            get_worker_engine(),
            get_embedding_provider(),
            get_chat_provider(),
            poll_seconds=settings.worker_poll_seconds,
        )
        worker_task = asyncio.create_task(worker.run_forever(stop))

    try:
        yield
    finally:
        if worker_task is not None:
            stop.set()
            with suppress(asyncio.CancelledError):
                await asyncio.wait_for(worker_task, timeout=10)
        readiness_checks.pop("database", None)
        await dispose_engines()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings)
    setup_sentry(settings)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Temporal Compliance RAG Engine — audits internal policies against "
        "in-force regulation for a jurisdiction as of a given date.",
        lifespan=_lifespan,
    )

    # Middleware runs in reverse add order: RequestContext wraps CORS wraps routes.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(v1_router, prefix="/api/v1")

    return app


app = create_app()
