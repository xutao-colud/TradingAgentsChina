from __future__ import annotations

import hashlib
import secrets
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import BoundedSemaphore, RLock
from typing import Callable, Iterator


class TestAccessCapacityError(RuntimeError):
    """Raised when the configured small-team test capacity is exhausted."""


@dataclass(frozen=True)
class TestAccessSession:
    token: str
    user_id: str
    display_name: str
    expires_at: float
    remember: bool

    def public_payload(self) -> dict[str, object]:
        return {
            "user_id": self.user_id,
            "display_name": self.display_name,
            "expires_at": self.expires_at,
            "remember": self.remember,
        }


class TestAccessSessionRegistry:
    """Process-local, deliberately unverified access sessions for a small test group."""

    def __init__(
        self,
        maximum_active_users: int,
        session_ttl_seconds: int,
        remember_ttl_seconds: int,
        *,
        clock: Callable[[], float] = time.time,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        if min(maximum_active_users, session_ttl_seconds, remember_ttl_seconds) < 1:
            raise ValueError("Small-team session limits must be positive")
        self.maximum_active_users = maximum_active_users
        self.session_ttl_seconds = session_ttl_seconds
        self.remember_ttl_seconds = remember_ttl_seconds
        self._clock = clock
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._sessions: dict[str, TestAccessSession] = {}
        self._lock = RLock()

    def login(self, account: object, password: object, remember: bool = False) -> TestAccessSession:
        display_name = str(account or "").strip()
        supplied_password = str(password or "")
        if not display_name:
            raise ValueError("请输入测试账号")
        if not supplied_password:
            raise ValueError("请输入测试密码")
        if len(display_name) > 120:
            raise ValueError("测试账号不得超过 120 个字符")

        now = self._clock()
        user_id = _stable_test_user_id(display_name)
        with self._lock:
            self._remove_expired(now)
            active_users = {item.user_id for item in self._sessions.values()}
            if user_id not in active_users and len(active_users) >= self.maximum_active_users:
                raise TestAccessCapacityError(
                    f"测试席位已满（最多 {self.maximum_active_users} 个活跃账号）"
                )
            token = self._token_factory()
            ttl = self.remember_ttl_seconds if remember else self.session_ttl_seconds
            session = TestAccessSession(
                token=token,
                user_id=user_id,
                display_name=display_name,
                expires_at=now + ttl,
                remember=remember,
            )
            self._sessions[token] = session
            return session

    def resolve(self, token: str | None) -> TestAccessSession | None:
        if not token:
            return None
        now = self._clock()
        with self._lock:
            self._remove_expired(now)
            return self._sessions.get(token)

    def logout(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._sessions.pop(token, None)

    def active_user_count(self) -> int:
        with self._lock:
            self._remove_expired(self._clock())
            return len({item.user_id for item in self._sessions.values()})

    def remaining_seconds(self, session: TestAccessSession) -> int:
        return max(1, int(session.expires_at - self._clock()))

    def _remove_expired(self, now: float) -> None:
        expired = [token for token, item in self._sessions.items() if item.expires_at <= now]
        for token in expired:
            self._sessions.pop(token, None)


class ResearchCapacityGate:
    """Bound expensive research jobs and expose process-lifetime, factual counters."""

    def __init__(self, maximum_concurrent_jobs: int) -> None:
        if maximum_concurrent_jobs < 1:
            raise ValueError("maximum_concurrent_jobs must be positive")
        self.maximum_concurrent_jobs = maximum_concurrent_jobs
        self._slots = BoundedSemaphore(maximum_concurrent_jobs)
        self._lock = RLock()
        self._active_jobs = 0
        self._started_jobs = 0
        self._completed_jobs = 0
        self._failed_jobs = 0
        self._analysis_jobs = 0
        self._opportunity_scans = 0
        self._model_explanations = 0
        self._started_at = time.time()

    @contextmanager
    def slot(self, job_type: str) -> Iterator[None]:
        if not self._slots.acquire(blocking=False):
            raise TestAccessCapacityError(
                f"当前重研判任务已达上限（{self.maximum_concurrent_jobs}），请等待已有任务完成"
            )
        with self._lock:
            self._active_jobs += 1
            self._started_jobs += 1
            if job_type == "analysis":
                self._analysis_jobs += 1
            elif job_type == "opportunity_scan":
                self._opportunity_scans += 1
        try:
            yield
        except Exception:
            with self._lock:
                self._failed_jobs += 1
            raise
        else:
            with self._lock:
                self._completed_jobs += 1
        finally:
            with self._lock:
                self._active_jobs -= 1
            self._slots.release()

    def record_model_explanation(self) -> None:
        with self._lock:
            self._model_explanations += 1

    def metrics(self) -> dict[str, int | float]:
        with self._lock:
            return {
                "maximum_concurrent_jobs": self.maximum_concurrent_jobs,
                "active_jobs": self._active_jobs,
                "started_jobs": self._started_jobs,
                "completed_jobs": self._completed_jobs,
                "failed_jobs": self._failed_jobs,
                "analysis_jobs": self._analysis_jobs,
                "opportunity_scans": self._opportunity_scans,
                "model_explanations": self._model_explanations,
                "started_at": self._started_at,
            }


class UserResearchAppPool:
    """Create one isolated research application per test alias."""

    def __init__(self, memory_root: str | Path, app_factory: Callable[[Path], object]) -> None:
        self.memory_root = Path(memory_root)
        self.memory_root.mkdir(parents=True, exist_ok=True)
        self.app_factory = app_factory
        self._apps: dict[str, object] = {}
        self._lock = RLock()

    def get(self, user_id: str) -> object:
        with self._lock:
            app = self._apps.get(user_id)
            if app is None:
                user_root = self.memory_root / "users" / user_id
                user_root.mkdir(parents=True, exist_ok=True)
                app = self.app_factory(user_root)
                self._apps[user_id] = app
            return app


def _stable_test_user_id(account: str) -> str:
    normalized = " ".join(account.casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]
