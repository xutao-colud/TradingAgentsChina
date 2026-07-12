from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class EvidenceSource:
    id: str
    title: str
    source_type: str
    as_of: str
    url: str | None = None


@dataclass(frozen=True)
class DailyPrice:
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
    turnover_rate: float


@dataclass(frozen=True)
class FundamentalSnapshot:
    revenue_growth_yoy: float
    profit_growth_yoy: float
    roe: float
    gross_margin: float
    debt_to_asset: float
    pe_ttm: float
    pb: float
    cashflow_quality: float
    forecast_revision: str


@dataclass(frozen=True)
class MoneyFlowSnapshot:
    main_net_inflow: float
    super_large_net_inflow: float
    margin_balance_change: float
    northbound_signal: str
    turnover_rate: float
    block_trade_signal: str


@dataclass(frozen=True)
class Announcement:
    title: str
    published_at: str
    priority: str
    sentiment: str
    summary: str
    source_id: str


@dataclass(frozen=True)
class MarketContext:
    index_name: str
    index_change_pct: float
    total_amount: float
    advancers: int
    decliners: int
    limit_up_count: int
    limit_down_count: int
    hot_money_cycle: str
    policy_themes: list[str]
    failed_breakout_rate: float = 0.0
    yesterday_limit_up_premium: float = 0.0
    max_consecutive_boards: int = 0
    first_board_count: int = 0
    second_board_success_rate: float = 0.0
    strong_stock_return: float = 0.0


@dataclass(frozen=True)
class StockProfile:
    symbol: str
    name: str
    industry: str
    board: str
    is_st: bool = False
    is_suspended: bool = False


@dataclass(frozen=True)
class AgentFinding:
    agent: str
    conclusion: str
    score: int
    confidence: float
    evidence: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    counterpoints: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SkillInsight:
    skill: str
    category: str
    stage: str
    score: int
    conclusion: str
    strategy: str
    evidence: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AnalysisInput:
    symbol: str
    analysis_date: str


@dataclass(frozen=True)
class AnalysisReport:
    symbol: str
    name: str
    analysis_date: str
    market_regime: str
    fundamental_score: int
    technical_score: int
    capital_flow_score: int
    sentiment_score: int
    theme_score: int
    risk_level: str
    conclusion: str
    confidence: float
    action_plan: str
    bull_case: list[str]
    bear_case: list[str]
    risk_factors: list[str]
    invalid_conditions: list[str]
    agent_findings: list[AgentFinding]
    evidence_sources: list[EvidenceSource]
    skill_insights: list[SkillInsight] = field(default_factory=list)
    active_playbook: str | None = None
    user_question: str | None = None
    realtime_quote: dict[str, Any] | None = None
    model_interpretation: str | None = None
    disclaimer: str = "研究分析输出，不构成投资建议或自动交易指令。"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def today_iso() -> str:
    return date.today().isoformat()
