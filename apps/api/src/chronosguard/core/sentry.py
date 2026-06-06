"""Sentry wiring with confidentiality scrubbing.

Name-based redaction alone leaks: exception args and ``extra`` payloads carry
no field names. The scrubber therefore truncates EVERY oversized string in
exception values, extras, and contexts — policy/regulatory text can never ride
an error report out of the system (docs/ARCHITECTURE.md §8.4).
"""

from typing import Any

from chronosguard.core.config import Settings

MAX_EVENT_STRING_CHARS = 200
_TRUNCATION_SUFFIX = "…<truncated>"


def _truncate(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_EVENT_STRING_CHARS:
        return value[:MAX_EVENT_STRING_CHARS] + _TRUNCATION_SUFFIX
    if isinstance(value, dict):
        return {key: _truncate(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_truncate(item) for item in value]
    return value


def scrub_event(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    for key in ("extra", "contexts", "breadcrumbs"):
        if key in event:
            event[key] = _truncate(event[key])
    for exception in event.get("exception", {}).get("values", []) or []:
        if exception.get("value"):
            exception["value"] = _truncate(exception["value"])
        for frame in exception.get("stacktrace", {}).get("frames", []) or []:
            if frame.get("vars"):
                frame["vars"] = _truncate(frame["vars"])
    if "request" in event:  # bodies may carry policy text — drop wholesale
        event["request"].pop("data", None)
    return event


def setup_sentry(settings: Settings) -> None:
    if not settings.sentry_dsn:
        return
    import sentry_sdk  # noqa: PLC0415 — only initialize when a DSN is configured

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.env,
        before_send=scrub_event,  # type: ignore[arg-type]  # Event is a dict at runtime
        send_default_pii=False,
        traces_sample_rate=0.1,
    )
