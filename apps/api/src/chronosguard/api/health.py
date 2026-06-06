"""Liveness and readiness endpoints (unversioned, unauthenticated).

``/healthz``: process is up — no dependencies, used for restart probes.
``/readyz``: dependencies are reachable — gates traffic. Checks register via
``readiness_checks`` so later chunks (DB, OpenAI) plug in without touching this file.
"""

from collections.abc import Awaitable, Callable

import structlog
from fastapi import APIRouter, Response, status

from chronosguard.schemas.health import CheckStatus, HealthStatus, ReadinessStatus

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["health"])

#: name -> async check. A check raising or returning False marks the app degraded.
readiness_checks: dict[str, Callable[[], Awaitable[bool]]] = {}


@router.get("/healthz", operation_id="liveness", response_model=HealthStatus)
async def healthz() -> HealthStatus:
    return HealthStatus()


@router.get(
    "/readyz",
    operation_id="readiness",
    response_model=ReadinessStatus,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessStatus}},
)
async def readyz(response: Response) -> ReadinessStatus:
    results: dict[str, CheckStatus] = {}
    for name, check in readiness_checks.items():
        try:
            results[name] = "ok" if await check() else "failed"
        except Exception:
            logger.exception("readiness_check_failed", check=name)
            results[name] = "failed"

    degraded = any(state == "failed" for state in results.values())
    if degraded:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessStatus(status="degraded" if degraded else "ok", checks=results)
