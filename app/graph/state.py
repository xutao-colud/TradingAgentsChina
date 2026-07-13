from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.report import (
    AhPremiumSnapshot,
    AshareMarketSignals,
    AgentFinding,
    Announcement,
    CapitalFlowObservation,
    DailyPrice,
    DataQualityReport,
    DragonTigerSeatRecord,
    EvidenceSource,
    FundamentalSnapshot,
    IndustryContext,
    IntradaySnapshot,
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
    user_question: str | None = None
    profile: StockProfile | None = None
    prices: list[DailyPrice] = field(default_factory=list)
    fundamentals: FundamentalSnapshot | None = None
    industry_context: IndustryContext | None = None
    money_flow: MoneyFlowSnapshot | None = None
    capital_flow_history: list[CapitalFlowObservation] = field(default_factory=list)
    dragon_tiger_history: list[DragonTigerSeatRecord] = field(default_factory=list)
    intraday: IntradaySnapshot | None = None
    market_signals: AshareMarketSignals | None = None
    announcements: list[Announcement] = field(default_factory=list)
    market_context: MarketContext | None = None
    ah_premium: AhPremiumSnapshot | None = None
    findings: list[AgentFinding] = field(default_factory=list)
    skill_insights: list[SkillInsight] = field(default_factory=list)
    evidence_sources: list[EvidenceSource] = field(default_factory=list)
    data_quality_reports: list[DataQualityReport] = field(default_factory=list)
    invalid_conditions: list[str] = field(default_factory=list)
    data_readiness: SkillInsight | None = None
    trading_profile: TradingProfile | None = None
