from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import date
import math
from typing import TypeVar


@dataclass(frozen=True)
class MarketBacktestObservation:
    available_at: str
    sentiment_cycle: str
    limit_up_count: int
    limit_down_count: int
    failed_breakout_rate: float
    source_id: str


@dataclass(frozen=True)
class ThemeBacktestObservation:
    available_at: str
    theme: str
    lifecycle: str
    strength_score: float
    source_id: str


@dataclass(frozen=True)
class ThemeMembershipObservation:
    symbol: str
    theme: str
    effective_from: str
    effective_to: str | None
    known_at: str
    source_id: str


@dataclass(frozen=True)
class StockBehaviorObservation:
    available_at: str
    symbol: str
    limit_status: str
    consecutive_boards: int
    main_net_inflow_3d: float
    theme_core_rank: int
    source_id: str


@dataclass(frozen=True)
class FundamentalBacktestObservation:
    symbol: str
    period_end: str
    announced_at: str
    revenue_growth_yoy: float
    profit_growth_yoy: float
    roe: float
    operating_cash_flow: float
    net_income: float
    total_assets: float
    total_liabilities: float
    total_equity: float
    announcement_risk: bool
    source_id: str

    @property
    def cashflow_quality(self) -> float | None:
        return self.operating_cash_flow / self.net_income if self.net_income != 0 else None

    @property
    def debt_to_asset(self) -> float:
        return self.total_liabilities / self.total_assets * 100


@dataclass(frozen=True)
class ConsensusBacktestObservation:
    available_at: str
    symbol: str
    revision_pct: float
    forward_profit_growth_yoy: float
    source_id: str


@dataclass(frozen=True)
class ValuationBacktestObservation:
    available_at: str
    symbol: str
    pe_ttm: float
    pb: float
    source_id: str


@dataclass(frozen=True)
class DividendBacktestObservation:
    announced_at: str
    symbol: str
    cash_dividend_per_share: float
    dividend_yield_pct: float
    payout_ratio_pct: float
    source_id: str


T = TypeVar("T")


@dataclass(frozen=True)
class PointInTimeDataset:
    """Historical facts queryable only after their recorded availability date."""

    symbol: str
    market: list[MarketBacktestObservation] = field(default_factory=list)
    themes: list[ThemeBacktestObservation] = field(default_factory=list)
    memberships: list[ThemeMembershipObservation] = field(default_factory=list)
    stock_behavior: list[StockBehaviorObservation] = field(default_factory=list)
    fundamentals: list[FundamentalBacktestObservation] = field(default_factory=list)
    consensus: list[ConsensusBacktestObservation] = field(default_factory=list)
    valuations: list[ValuationBacktestObservation] = field(default_factory=list)
    dividends: list[DividendBacktestObservation] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("point-in-time dataset requires a symbol")
        for collection in (
            self.market,
            self.themes,
            self.memberships,
            self.stock_behavior,
            self.fundamentals,
            self.consensus,
            self.valuations,
            self.dividends,
        ):
            for item in collection:
                _validate_record(item)
        for item in self.fundamentals:
            if _parse_date(item.period_end) > _parse_date(item.announced_at):
                raise ValueError("fundamental period_end cannot be later than announced_at")
            if item.total_assets <= 0:
                raise ValueError("fundamental total_assets must be positive")
        for item in self.market:
            if item.limit_up_count < 0 or item.limit_down_count < 0 or not 0 <= item.failed_breakout_rate <= 100:
                raise ValueError("market breadth values are outside their valid range")
        for item in self.stock_behavior:
            if item.consecutive_boards < 0 or item.theme_core_rank < 1:
                raise ValueError("stock behavior board count or core rank is invalid")
        for item in self.valuations:
            if item.pe_ttm <= 0 or item.pb <= 0:
                raise ValueError("valuation observations require positive PE and PB")
        for item in self.dividends:
            if min(item.cash_dividend_per_share, item.dividend_yield_pct, item.payout_ratio_pct) < 0:
                raise ValueError("dividend observations cannot contain negative values")
        for item in self.memberships:
            if item.effective_to and _parse_date(item.effective_from) > _parse_date(item.effective_to):
                raise ValueError("theme membership effective_from cannot be later than effective_to")
        symbol_records = [
            *self.memberships,
            *self.stock_behavior,
            *self.fundamentals,
            *self.consensus,
            *self.valuations,
            *self.dividends,
        ]
        if any(item.symbol != self.symbol for item in symbol_records):
            raise ValueError("point-in-time dataset contains records for a different symbol")

    def coverage(self) -> set[str]:
        collections = {
            "market_sentiment_history": self.market,
            "theme_history": self.themes,
            "theme_membership_history": self.memberships,
            "stock_behavior_history": self.stock_behavior,
            "point_in_time_fundamentals": self.fundamentals,
            "consensus_history": self.consensus,
            "valuation_history": self.valuations,
            "dividend_history": self.dividends,
        }
        return {name for name, values in collections.items() if values}

    def source_ids(self) -> list[str]:
        identifiers = [
            item.source_id
            for collection in (
                self.market,
                self.themes,
                self.memberships,
                self.stock_behavior,
                self.fundamentals,
                self.consensus,
                self.valuations,
                self.dividends,
            )
            for item in collection
        ]
        return list(dict.fromkeys(identifiers))

    def latest_market(self, as_of: str) -> MarketBacktestObservation | None:
        return _latest_available(self.market, as_of, "available_at")

    def active_themes(self, as_of: str) -> list[str]:
        cutoff = _parse_date(as_of)
        return sorted({
            item.theme
            for item in self.memberships
            if _parse_date(item.known_at) <= cutoff
            and _parse_date(item.effective_from) <= cutoff
            and (item.effective_to is None or cutoff <= _parse_date(item.effective_to))
        })

    def latest_theme(self, theme: str, as_of: str) -> ThemeBacktestObservation | None:
        return _latest_available([item for item in self.themes if item.theme == theme], as_of, "available_at")

    def latest_stock_behavior(self, as_of: str) -> StockBehaviorObservation | None:
        return _latest_available(self.stock_behavior, as_of, "available_at")

    def latest_fundamental(self, as_of: str) -> FundamentalBacktestObservation | None:
        return _latest_available(self.fundamentals, as_of, "announced_at")

    def latest_consensus(self, as_of: str) -> ConsensusBacktestObservation | None:
        return _latest_available(self.consensus, as_of, "available_at")

    def latest_valuation(self, as_of: str) -> ValuationBacktestObservation | None:
        return _latest_available(self.valuations, as_of, "available_at")

    def latest_dividend(self, as_of: str) -> DividendBacktestObservation | None:
        return _latest_available(self.dividends, as_of, "announced_at")


def _latest_available(items: list[T], as_of: str, date_field: str) -> T | None:
    cutoff = _parse_date(as_of)
    available = [item for item in items if _parse_date(str(getattr(item, date_field))) <= cutoff]
    return max(available, key=lambda item: _parse_date(str(getattr(item, date_field))), default=None)


def _validate_record(item: object) -> None:
    values = {item_field.name: getattr(item, item_field.name) for item_field in fields(item)}
    if not str(values.get("source_id", "")).strip():
        raise ValueError(f"{type(item).__name__} requires source_id")
    if any(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and not math.isfinite(float(value))
        for value in values.values()
    ):
        raise ValueError(f"{type(item).__name__} contains a non-finite number")
    for field_name in ("available_at", "announced_at", "period_end", "effective_from", "effective_to", "known_at"):
        value = values.get(field_name)
        if value is not None:
            _parse_date(str(value))


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid point-in-time date: {value}") from exc
