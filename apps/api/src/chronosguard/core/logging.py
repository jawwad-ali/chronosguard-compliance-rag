"""structlog configuration.

JSON renderer in prod, pretty console locally. ``request_id`` and ``tenant_id``
flow into every log line via contextvars bound by middleware — zero plumbing in
business code. Confidential payloads are redacted by key name before rendering.
"""

import logging

import structlog
from structlog.typing import EventDict, WrappedLogger

from chronosguard.core.config import Settings

#: Values under these keys never reach logs in full — confidentiality rule.
REDACTED_KEYS: frozenset[str] = frozenset({"policy_text", "content", "embedding", "raw_markdown"})
_REDACTION_PREVIEW_LEN = 24


def redact_confidential(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """Replace confidential values with a length-prefixed marker."""
    for key in REDACTED_KEYS & event_dict.keys():
        value = event_dict[key]
        text = value if isinstance(value, str) else repr(value)
        event_dict[key] = f"<redacted len={len(text)} preview={text[:_REDACTION_PREVIEW_LEN]!r}>"
    return event_dict


def setup_logging(settings: Settings) -> None:
    level = logging.getLevelNamesMapping().get(settings.log_level.upper(), logging.INFO)

    renderer: structlog.typing.Processor
    if settings.env == "local":
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_confidential,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )

    # Route stdlib logging (uvicorn, sqlalchemy, alembic) through the same level.
    logging.basicConfig(level=level, format="%(message)s")
