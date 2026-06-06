"""Application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from chronosguard import __version__
from chronosguard.api.health import router as health_router
from chronosguard.api.v1 import v1_router
from chronosguard.core.config import Settings, get_settings
from chronosguard.core.errors import register_exception_handlers
from chronosguard.core.logging import setup_logging
from chronosguard.core.middleware import RequestContextMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Temporal Compliance RAG Engine — audits internal policies against "
        "in-force regulation for a jurisdiction as of a given date.",
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
