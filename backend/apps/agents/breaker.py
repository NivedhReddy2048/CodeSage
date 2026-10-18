"""A small circuit breaker, per provider.

Why bother on a hobby project: when Groq's daily quota is exhausted, every review
would otherwise spend its full retry budget - three attempts with exponential
backoff - discovering the same 429 before falling back. That is roughly fourteen
wasted seconds per review, on every review, for the rest of the day.

Opening the circuit after repeated failures makes the fallback immediate, and
half-open probing means recovery needs no intervention.

Deliberately in-process rather than shared through Redis: spec section 7 runs one
co-located worker, so process-local state is the whole system's state. A multi-worker
deployment would want this in Redis, which is a note for phase 7 rather than
speculative complexity now.
"""

import threading
import time


class CircuitState:
    CLOSED = "closed"  # normal
    OPEN = "open"  # failing; skip it
    HALF_OPEN = "half_open"  # probing for recovery


class CircuitBreaker:
    def __init__(self, failure_threshold=3, reset_seconds=300.0, name="breaker"):
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self.name = name
        self._failures = 0
        self._opened_at = None
        self._lock = threading.Lock()

    @property
    def state(self):
        with self._lock:
            return self._state_locked()

    def _state_locked(self):
        if self._opened_at is None:
            return CircuitState.CLOSED
        if time.monotonic() - self._opened_at >= self.reset_seconds:
            # Cooled off: allow exactly one trial call through.
            return CircuitState.HALF_OPEN
        return CircuitState.OPEN

    def allows(self):
        """Whether a call may be attempted right now."""
        return self.state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def record_success(self):
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def record_failure(self):
        with self._lock:
            if self._state_locked() == CircuitState.HALF_OPEN:
                # The probe failed; start the cooldown again rather than letting
                # every subsequent call through.
                self._opened_at = time.monotonic()
                return

            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._opened_at = time.monotonic()

    def reset(self):
        with self._lock:
            self._failures = 0
            self._opened_at = None


# One breaker per provider name, shared across reviews in this process.
_breakers = {}
_registry_lock = threading.Lock()


def get_breaker(name, failure_threshold=3, reset_seconds=300.0):
    with _registry_lock:
        breaker = _breakers.get(name)
        if breaker is None:
            breaker = CircuitBreaker(failure_threshold, reset_seconds, name)
            _breakers[name] = breaker
        return breaker


def reset_all():
    """Used by tests, so breaker state cannot leak between them."""
    with _registry_lock:
        for breaker in _breakers.values():
            breaker.reset()
        _breakers.clear()
