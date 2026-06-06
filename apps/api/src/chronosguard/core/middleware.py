"""Request-context middleware (pure ASGI — avoids BaseHTTPMiddleware pitfalls).

Reads or mints ``X-Request-ID``, binds it into structlog contextvars so every
log line in the request carries it, and echoes it on the response for
client-side correlation. ``tenant_id`` is bound later by the auth dependency.
"""

from uuid import uuid4

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = Headers(scope=scope).get(REQUEST_ID_HEADER) or uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        await self.app(scope, receive, send_with_request_id)


def current_request_id() -> str:
    """The request id bound by the middleware ('-' outside a request)."""
    value = structlog.contextvars.get_contextvars().get("request_id", "-")
    return str(value)
