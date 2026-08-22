"""Minimal in-memory circuit breaker.

Opens after `failure_threshold` consecutive failures and stays open for
`reset_timeout` seconds, refusing calls immediately during that window
instead of letting them queue up against a rate-limited/down API. After
the cooldown it allows exactly one trial call (half-open); success
closes the circuit, failure reopens it.
"""
import time
from enum import Enum


class State(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    pass


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, reset_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.state = State.CLOSED
        self.failure_count = 0
        self.opened_at: float | None = None

    def allow_request(self) -> bool:
        if self.state == State.OPEN:
            if self.opened_at is not None and (
                time.monotonic() - self.opened_at
            ) >= self.reset_timeout:
                self.state = State.HALF_OPEN
                return True
            return False
        return True

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = State.CLOSED
        self.opened_at = None

    def record_failure(self) -> None:
        self.failure_count += 1
        if self.state == State.HALF_OPEN or self.failure_count >= self.failure_threshold:
            self.state = State.OPEN
            self.opened_at = time.monotonic()
