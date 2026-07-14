from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class TenantContext:
    tenant_id: str
    user_id: str
    roles: frozenset[str] = field(default_factory=lambda: frozenset({"member"}))

    def require(self, role: str) -> None:
        if role not in self.roles:
            raise PermissionError(f"Tenant role required: {role}")


@dataclass(frozen=True)
class AnalyticsConsent:
    tenant_id: str
    user_id: str
    scope: Literal["strategy_outcome_aggregate"]
    granted: bool
    policy_version: str
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True)
class StrategyOutcomeRecord:
    tenant_id: str
    user_id: str
    analysis_report_id: str
    playbook_id: str
    playbook_fit_score: int
    outcome_return_pct: float
    outcome_days: int
    aggregate_consent: bool
    outcome_source: Literal["manual", "broker_import", "simulated"] = "manual"
    market_regime: str = "unknown"
    agent_scores: dict[str, int] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
