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
    snapshot_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DataQualityIssue:
    code: str
    severity: str
    message: str
    field: str | None = None
    record_index: int | None = None


@dataclass(frozen=True)
class DataQualityReport:
    provider: str
    dataset: str
    status: str
    checked_records: int
    valid_records: int
    completeness: float
    as_of: str | None = None
    snapshot_ids: list[str] = field(default_factory=list)
    issues: list[DataQualityIssue] = field(default_factory=list)
    blocking: bool = False


@dataclass(frozen=True)
class DailyPrice:
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float | None
    turnover_rate: float | None


@dataclass(frozen=True)
class AhPremiumSnapshot:
    data_status: str
    trade_date: str
    a_symbol: str
    h_symbol: str | None = None
    a_close: float | None = None
    h_close: float | None = None
    ah_comparison: float | None = None
    ah_premium_pct: float | None = None
    source_id: str | None = None
    unavailable_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class IntradayBar:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float


@dataclass(frozen=True)
class OrderBookLevel:
    price: float
    volume: float


@dataclass(frozen=True)
class IntradaySnapshot:
    data_status: str
    as_of: str
    bars: list[IntradayBar] = field(default_factory=list)
    bids: list[OrderBookLevel] = field(default_factory=list)
    asks: list[OrderBookLevel] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    unavailable_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FundamentalSnapshot:
    revenue_growth_yoy: float | None
    profit_growth_yoy: float | None
    roe: float | None
    gross_margin: float | None
    debt_to_asset: float | None
    pe_ttm: float | None
    pb: float | None
    cashflow_quality: float | None
    forecast_revision: str
    revenue: float | None = None
    net_income: float | None = None
    operating_cash_flow: float | None = None
    total_assets: float | None = None
    total_equity: float | None = None
    accounts_receivable: float | None = None
    inventory: float | None = None
    statement_as_of: str | None = None
    peer_medians: dict[str, float] = field(default_factory=dict)
    peer_sample_sizes: dict[str, int] = field(default_factory=dict)
    peer_as_of: str | None = None
    peer_source_id: str | None = None
    peer_unavailable_reasons: list[str] = field(default_factory=list)
    net_profit_margin: float | None = None
    asset_turnover: float | None = None
    equity_multiplier: float | None = None
    goodwill_ratio: float | None = None
    goodwill_as_of: str | None = None
    goodwill_source_id: str | None = None
    pledge_ratio: float | None = None
    pledge_as_of: str | None = None
    pledge_source_id: str | None = None
    deducted_net_income: float | None = None
    non_recurring_profit_impact: float | None = None
    non_recurring_profit_ratio: float | None = None
    scope_limitations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class IndustryFlowObservation:
    trade_date: str
    industry: str
    industry_code: str
    net_amount: float
    pct_change: float | None = None
    company_count: int | None = None
    source_id: str = "industry-flow-unavailable"


@dataclass(frozen=True)
class IndustryValuationObservation:
    trade_date: str
    pe_ttm_median: float | None
    pb_median: float | None
    sample_size: int
    source_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class IndustryChainNode:
    stage: str
    industry: str
    source_id: str


@dataclass(frozen=True)
class IndustryContext:
    data_status: str
    industry: str
    as_of: str
    flow_observations: list[IndustryFlowObservation] = field(default_factory=list)
    valuation_history: list[IndustryValuationObservation] = field(default_factory=list)
    chain_nodes: list[IndustryChainNode] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    unavailable_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MoneyFlowSnapshot:
    main_net_inflow: float | None
    super_large_net_inflow: float | None
    margin_balance_change: float | None
    northbound_signal: str
    turnover_rate: float | None
    block_trade_signal: str
    large_net_inflow: float | None = None
    medium_net_inflow: float | None = None
    small_net_inflow: float | None = None
    as_of: str | None = None
    northbound_net_inflow: float | None = None
    # Independent fallback derived from exchange ticks.  This is deliberately
    # separate from vendor-defined "main force" flow: an up-tick minus
    # down-tick amount is observable, but it must never be relabelled as
    # institutional or main-capital activity.
    trade_direction_net_inflow: float | None = None
    trade_direction_gross_amount: float | None = None
    flow_method: str | None = None


@dataclass(frozen=True)
class CapitalFlowObservation:
    trade_date: str
    main_net_inflow: float | None = None
    northbound_holding_change: float | None = None
    margin_balance: float | None = None
    source_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Announcement:
    title: str
    published_at: str
    priority: str
    sentiment: str
    summary: str
    source_id: str
    event_type: str = "general"
    report_period: str | None = None
    forecast_net_profit_min_yuan: float | None = None
    forecast_net_profit_max_yuan: float | None = None
    actual_net_profit_yuan: float | None = None
    first_announced_at: str | None = None
    url: str | None = None
    published_timestamp: str | None = None
    supporting_source_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DragonTigerSeatRecord:
    trade_date: str
    reason: str
    seat_name: str
    side: str
    buy_amount: float | None
    sell_amount: float | None
    net_buy_amount: float | None
    buy_rate: float | None = None
    sell_rate: float | None = None
    source_id: str = "dragon-tiger-seat-unavailable"


@dataclass(frozen=True)
class DragonTigerRecord:
    trade_date: str
    reason: str
    net_buy_amount: float
    institution_net_amount: float | None
    buy_seats: list[str] = field(default_factory=list)
    sell_seats: list[str] = field(default_factory=list)
    source_id: str = "dragon-tiger-unavailable"
    seat_records: list[DragonTigerSeatRecord] = field(default_factory=list)


@dataclass(frozen=True)
class MarginFinancingRecord:
    trade_date: str
    margin_balance: float | None
    securities_balance: float | None
    margin_buy_amount: float | None
    margin_repay_amount: float | None
    source_id: str = "margin-unavailable"


@dataclass(frozen=True)
class NorthboundHoldingRecord:
    trade_date: str
    holding_quantity: float | None
    holding_value: float | None
    holding_change: float | None
    source_id: str = "northbound-unavailable"


@dataclass(frozen=True)
class CorporateEvent:
    event_type: str
    title: str
    published_at: str
    impact: str
    summary: str
    source_id: str
    report_period: str | None = None
    forecast_net_profit_min_yuan: float | None = None
    forecast_net_profit_max_yuan: float | None = None
    actual_net_profit_yuan: float | None = None
    first_announced_at: str | None = None
    url: str | None = None
    published_timestamp: str | None = None
    supporting_source_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AshareMarketSignals:
    data_status: str
    dragon_tiger: list[DragonTigerRecord] = field(default_factory=list)
    margin_financing: MarginFinancingRecord | None = None
    northbound_holding: NorthboundHoldingRecord | None = None
    corporate_events: list[CorporateEvent] = field(default_factory=list)
    evidence_sources: list[EvidenceSource] = field(default_factory=list)
    unavailable_reasons: list[str] = field(default_factory=list)
    quality_reports: list[DataQualityReport] = field(default_factory=list)


@dataclass(frozen=True)
class MarketContext:
    index_name: str
    index_change_pct: float | None
    total_amount: float | None
    advancers: int | None
    decliners: int | None
    limit_up_count: int | None
    limit_down_count: int | None
    hot_money_cycle: str
    policy_themes: list[str]
    failed_breakout_rate: float | None = None
    yesterday_limit_up_premium: float | None = None
    max_consecutive_boards: int | None = None
    first_board_count: int | None = None
    second_board_success_rate: float | None = None
    strong_stock_return: float | None = None
    sealed_limit_up_rate: float | None = None
    one_price_limit_up_count: int | None = None
    broken_limit_up_count: int | None = None
    board_ladder: dict[str, int] = field(default_factory=dict)
    sentiment_history: list["MarketSentimentObservation"] = field(default_factory=list)
    median_stock_change_pct: float | None = None
    amount_weighted_change_pct: float | None = None
    top_amount_concentration_pct: float | None = None
    data_status: str = "verified"
    as_of: str | None = None
    unavailable_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class StockProfile:
    symbol: str
    name: str
    industry: str
    board: str
    is_st: bool = False
    is_suspended: bool = False
    concepts: list[str] = field(default_factory=list)
    concept_source_id: str | None = None
    list_date: str | None = None
    major_shareholder_reduction: bool | None = None
    major_shareholder_reduction_count: int | None = None
    major_shareholder_reduction_as_of: str | None = None
    major_shareholder_reduction_source_ids: list[str] = field(default_factory=list)
    inquiry_count: int | None = None
    inquiry_as_of: str | None = None
    inquiry_source_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MarketSentimentObservation:
    trade_date: str
    limit_up_count: int
    limit_down_count: int
    failed_breakout_rate: float
    yesterday_limit_up_premium: float
    max_consecutive_boards: int
    first_board_count: int
    second_board_success_rate: float
    strong_stock_return: float
    total_amount: float | None = None
    advancers: int | None = None
    decliners: int | None = None
    sealed_limit_up_rate: float | None = None
    one_price_limit_up_count: int | None = None
    broken_limit_up_count: int | None = None
    board_ladder: dict[str, int] = field(default_factory=dict)
    median_stock_change_pct: float | None = None
    amount_weighted_change_pct: float | None = None
    top_amount_concentration_pct: float | None = None


@dataclass(frozen=True)
class AgentFinding:
    agent: str
    conclusion: str
    score: int
    confidence: float
    evidence: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    counterpoints: list[str] = field(default_factory=list)
    invalidation_conditions: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


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
    data_status: str
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
    data_quality_reports: list[DataQualityReport] = field(default_factory=list)
    skill_insights: list[SkillInsight] = field(default_factory=list)
    active_playbook: str | None = None
    user_question: str | None = None
    realtime_quote: dict[str, Any] | None = None
    decision_brief: dict[str, Any] = field(default_factory=dict)
    model_interpretation: str | None = None
    model_execution: dict[str, Any] | None = None
    rule_version: str = "unknown"
    config_source: str = "unknown"
    analysis_level: int = 3
    disclaimer: str = "研究分析输出，不构成投资建议或自动交易指令。"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def today_iso() -> str:
    return date.today().isoformat()
