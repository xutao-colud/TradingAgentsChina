from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class TradingProfile:
    style: str = "趋势+价值混合"
    risk_level: str = "中"
    holding_period: str = "1-3个月"
    preferred_setups: list[str] = field(default_factory=lambda: ["趋势回踩", "业绩增长", "资金温和流入"])
    avoid_patterns: list[str] = field(default_factory=lambda: ["ST/*ST", "高位情绪接力", "纯概念炒作"])
    favorite_themes: list[str] = field(default_factory=list)
    review_rules: list[str] = field(default_factory=list)
    active_playbook: str = "trend_core"
    version: int = 1
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TradingProfile":
        defaults = cls()
        merged = defaults.to_dict()
        merged.update(data)
        return cls(**merged)


@dataclass(frozen=True)
class MemoryEvent:
    event_type: str
    payload: dict[str, Any]
    symbol: str | None = None
    analysis_date: str | None = None
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FeedbackEvent:
    symbol: str
    feedback_type: str
    user_comment: str
    analysis_report_id: str | None = None
    outcome_return_pct: float | None = None
    outcome_days: int | None = None
    learned_rule: str | None = None
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
