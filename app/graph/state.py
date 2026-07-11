from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.report import (
    AgentFinding,
    Announcement,
    DailyPrice,
    EvidenceSource,
    FundamentalSnapshot,
    MarketContext,
    MoneyFlowSnapshot,
    SkillInsight,
    StockProfile,
)
from app.memory.models import TradingProfile


@dataclass
class ResearchState:
    symbol: str
    analysis_date: str
    profile: StockProfile | None = None
    prices: list[DailyPrice] = field(default_factory=list)
    fundamentals: FundamentalSnapshot | None = None
    money_flow: MoneyFlowSnapshot | None = None
    announcements: list[Announcement] = field(default_factory=list)
    market_context: MarketContext | None = None
    findings: list[AgentFinding] = field(default_factory=list)
    skill_insights: list[SkillInsight] = field(default_factory=list)
    evidence_sources: list[EvidenceSource] = field(default_factory=list)
    invalid_conditions: list[str] = field(default_factory=list)
    trading_profile: TradingProfile | None = None
