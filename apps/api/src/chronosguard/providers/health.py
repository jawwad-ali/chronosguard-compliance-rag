"""Provider circuit breaker — an OpenAI outage must degrade loudly, not queue
jobs that will dead-letter (docs/ARCHITECTURE.md §4.4).

After ``FAILURE_THRESHOLD`` consecutive failures the breaker opens for
``COOLDOWN_SECONDS``: audit acceptance returns 503 instead of enqueueing work
that cannot complete. Any success closes it.
"""

import threading
import time
from dataclasses import dataclass, field

FAILURE_THRESHOLD = 3
COOLDOWN_SECONDS = 60.0


@dataclass
class ProviderHealth:
    failure_threshold: int = FAILURE_THRESHOLD
    cooldown_seconds: float = COOLDOWN_SECONDS
    _consecutive_failures: int = 0
    _opened_at: float | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.failure_threshold:
                self._opened_at = time.monotonic()

    @property
    def is_open(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return False
            if time.monotonic() - self._opened_at >= self.cooldown_seconds:
                # Half-open: allow the next attempt through to probe recovery.
                self._opened_at = None
                self._consecutive_failures = 0
                return False
            return True


#: Process-wide breaker for the chat provider (the audit-critical dependency).
chat_health = ProviderHealth()
