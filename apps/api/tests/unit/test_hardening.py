"""C8 hardening units: circuit breaker, Sentry scrubbing, connection budget."""

import pytest

from chronosguard.core.config import Settings
from chronosguard.core.sentry import MAX_EVENT_STRING_CHARS, scrub_event
from chronosguard.main import _assert_connection_budget
from chronosguard.providers.health import ProviderHealth


class TestCircuitBreaker:
    def test_opens_after_threshold_consecutive_failures(self) -> None:
        health = ProviderHealth(failure_threshold=3, cooldown_seconds=60)
        for _ in range(2):
            health.record_failure()
        assert not health.is_open
        health.record_failure()
        assert health.is_open

    def test_success_resets_the_count(self) -> None:
        health = ProviderHealth(failure_threshold=3, cooldown_seconds=60)
        health.record_failure()
        health.record_failure()
        health.record_success()
        health.record_failure()
        assert not health.is_open

    def test_half_opens_after_cooldown(self) -> None:
        health = ProviderHealth(failure_threshold=1, cooldown_seconds=0.0)
        health.record_failure()
        assert not health.is_open  # cooldown of zero ⇒ immediately probe again


class TestSentryScrubbing:
    def test_truncates_oversized_strings_everywhere(self) -> None:
        secret_policy = "CONFIDENTIAL " * 100
        event = {
            "extra": {"policy_text": secret_policy},
            "exception": {
                "values": [
                    {
                        "value": f"IntegrityError: row ({secret_policy})",
                        "stacktrace": {"frames": [{"vars": {"body": secret_policy}}]},
                    }
                ]
            },
            "request": {"data": secret_policy, "url": "/api/v1/audits"},
        }
        scrubbed = scrub_event(event, {})
        assert len(scrubbed["extra"]["policy_text"]) <= MAX_EVENT_STRING_CHARS + 20
        assert len(scrubbed["exception"]["values"][0]["value"]) <= MAX_EVENT_STRING_CHARS + 40
        frame_vars = scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]["vars"]
        assert len(frame_vars["body"]) <= MAX_EVENT_STRING_CHARS + 20
        assert "data" not in scrubbed["request"]  # bodies dropped wholesale
        assert scrubbed["request"]["url"] == "/api/v1/audits"

    def test_short_values_pass_untouched(self) -> None:
        event = {"extra": {"run_id": 42, "note": "short"}}
        assert scrub_event(event, {}) == {"extra": {"run_id": 42, "note": "short"}}


class TestConnectionBudget:
    def test_within_budget_passes(self) -> None:
        _assert_connection_budget(Settings(db_pool_size=5, db_max_overflow=5))

    def test_over_budget_refuses_startup(self) -> None:
        with pytest.raises(ValueError, match="exceeds DB_CONNECTION_BUDGET"):
            _assert_connection_budget(
                Settings(db_pool_size=80, db_max_overflow=20, db_connection_budget=60)
            )
