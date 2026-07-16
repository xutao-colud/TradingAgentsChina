from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from app.config.runtime import load_runtime_settings


@dataclass
class _HealthState:
    consecutive_failures: int = 0
    blocked_until: datetime | None = None


class ProviderCircuitBreaker:
    """Process-local circuit breaker keyed by provider and dataset."""

    def __init__(self, now: Callable[[], datetime] | None = None) -> None:
        config = load_runtime_settings().get("providers", "high_availability", "circuit_breaker")
        self.failure_threshold = int(config["failure_threshold"])
        self.cooldown_seconds = int(config["cooldown_seconds"])
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._states: dict[tuple[str, str], _HealthState] = {}

    def allows(self, provider: str, dataset: str) -> bool:
        state = self._states.get((provider, dataset))
        if state is None or state.blocked_until is None:
            return True
        if self._now() >= state.blocked_until:
            state.blocked_until = None
            state.consecutive_failures = 0
            return True
        return False

    def record(self, provider: str, dataset: str, *, succeeded: bool) -> None:
        state = self._states.setdefault((provider, dataset), _HealthState())
        if succeeded:
            state.consecutive_failures = 0
            state.blocked_until = None
            return
        state.consecutive_failures += 1
        if state.consecutive_failures >= self.failure_threshold:
            state.blocked_until = self._now() + timedelta(seconds=self.cooldown_seconds)
