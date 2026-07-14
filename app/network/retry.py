from __future__ import annotations

import time
from dataclasses import dataclass
from subprocess import TimeoutExpired
from typing import Callable, TypeVar
from urllib.error import HTTPError, URLError

from app.config.runtime import load_runtime_settings


T = TypeVar("T")


class RetryExhaustedError(OSError):
    """A transient provider request failed after every configured attempt."""

    def __init__(self, operation_name: str, attempts: int, last_error: Exception) -> None:
        self.operation_name = operation_name
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(f"{operation_name} failed after {attempts} attempts: {last_error}")


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int
    initial_backoff_seconds: float
    max_backoff_seconds: float

    @classmethod
    def from_runtime(cls) -> "RetryPolicy":
        config = load_runtime_settings().get("runtime", "network_retry")
        return cls(
            max_attempts=int(config["max_attempts"]),
            initial_backoff_seconds=float(config["initial_backoff_seconds"]),
            max_backoff_seconds=float(config["max_backoff_seconds"]),
        )

    def delay_after(self, failed_attempt: int) -> float:
        return min(self.max_backoff_seconds, self.initial_backoff_seconds * (2 ** (failed_attempt - 1)))


def retry_call(
    operation: Callable[[], T],
    *,
    operation_name: str,
    policy: RetryPolicy | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run an idempotent read operation with bounded retries.

    Semantic errors, permission failures, and malformed requests are never
    retried. They must remain visible to provider quality checks.
    """

    active_policy = policy or RetryPolicy.from_runtime()
    for attempt in range(1, active_policy.max_attempts + 1):
        try:
            return operation()
        except Exception as exc:
            if not is_retryable_exception(exc):
                raise
            if attempt >= active_policy.max_attempts:
                raise RetryExhaustedError(operation_name, attempt, exc) from exc
            sleep(active_policy.delay_after(attempt))
    raise AssertionError("retry loop must return or raise")


def is_retryable_exception(exc: Exception) -> bool:
    if isinstance(exc, HTTPError):
        return exc.code in {408, 425, 429, 500, 502, 503, 504}
    message = str(exc).lower()
    permanent_markers = (
        "permission denied", "access is denied", "forbidden", "unauthorized",
        "invalid token", "invalid api", "not support", "参数错误", "权限不足",
    )
    if any(marker in message for marker in permanent_markers):
        return False
    if isinstance(exc, (TimeoutError, TimeoutExpired, ConnectionError, URLError, OSError)):
        return True
    transient_markers = (
        "timeout", "timed out", "temporar", "connection reset", "connection aborted",
        "connection refused", "network", "rate limit", "too many requests", "http 429",
        "http 500", "http 502", "http 503", "http 504",
    )
    return any(marker in message for marker in transient_markers)
