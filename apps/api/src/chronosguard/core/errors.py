"""Domain exception hierarchy + RFC 9457 problem+json handlers.

Services raise domain exceptions; one set of global handlers translates them.
Clients see exactly one error shape (``ProblemDetail``). Internals (stack
traces, SQL, upstream errors) are logged with the request id, never returned.
"""

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from chronosguard.core.middleware import current_request_id
from chronosguard.schemas.problem import FieldError, ProblemDetail

logger = structlog.get_logger(__name__)

PROBLEM_CONTENT_TYPE = "application/problem+json"


class AppError(Exception):
    """Base domain error. Subclasses pin status code + title."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    title: str = "Internal Server Error"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail
        super().__init__(detail or self.title)


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    title = "Unauthorized"


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    title = "Forbidden"


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    title = "Not Found"

    def __init__(self, resource: str, identifier: object = None) -> None:
        detail = f"{resource} not found" + (f": {identifier}" if identifier is not None else "")
        super().__init__(detail)


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    title = "Conflict"


class UnprocessableError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    title = "Unprocessable Entity"


class RateLimitedError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    title = "Too Many Requests"


class ProviderError(AppError):
    """Upstream AI provider failure — details are logged, never leaked."""

    status_code = status.HTTP_502_BAD_GATEWAY
    title = "Upstream AI Error"


class ServiceUnavailableError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    title = "Service Unavailable"


def _problem_response(
    *,
    status_code: int,
    title: str,
    detail: str | None = None,
    instance: str | None = None,
    errors: list[FieldError] | None = None,
) -> JSONResponse:
    problem = ProblemDetail(
        title=title,
        status=status_code,
        detail=detail,
        instance=instance,
        request_id=current_request_id(),
        errors=errors,
    )
    return JSONResponse(
        status_code=status_code,
        content=problem.model_dump(exclude_none=True),
        media_type=PROBLEM_CONTENT_TYPE,
    )


async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    logger.warning(
        "app_error", error_type=type(exc).__name__, status=exc.status_code, detail=exc.detail
    )
    return _problem_response(
        status_code=exc.status_code,
        title=exc.title,
        detail=exc.detail,
        instance=str(request.url.path),
    )


async def _handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return _problem_response(
        status_code=exc.status_code,
        title=str(exc.detail),
        instance=str(request.url.path),
    )


async def _handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        FieldError(
            loc=".".join(str(part) for part in err.get("loc", ())),
            msg=str(err.get("msg", "invalid")),
            type=str(err.get("type", "value_error")),
        )
        for err in exc.errors()
    ]
    return _problem_response(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        title="Validation Error",
        detail="Request failed validation.",
        instance=str(request.url.path),
        errors=errors,
    )


async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    # Full traceback to logs/Sentry with request id; generic message to the client.
    logger.exception("unhandled_error", path=str(request.url.path))
    return _problem_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        title="Internal Server Error",
        instance=str(request.url.path),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _handle_validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _handle_unexpected)
