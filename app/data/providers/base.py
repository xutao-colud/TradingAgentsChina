from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.data.raw_snapshots import RawDataSnapshot

from app.schemas.report import (
    AhPremiumSnapshot,
    AshareMarketSignals,
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
    StockProfile,
)
from app.rules.special_instruments import ConvertibleBondSnapshot


@dataclass(frozen=True)
class ProviderCapabilities:
    provider: str
    datasets: frozenset[str]
    persists_raw_snapshots: bool

    def supports(self, dataset: str) -> bool:
        return dataset in self.datasets


class ProviderAdapter(ABC):
    data_mode = "production"

    def get_provider_capabilities(self) -> list[ProviderCapabilities]:
        return []

    def get_raw_snapshots(self, symbol: str, analysis_date: str) -> list[RawDataSnapshot]:
        return []

    def get_data_quality_reports(self, symbol: str, analysis_date: str) -> list[DataQualityReport]:
        return []


class MarketDataProvider(ProviderAdapter, ABC):
    """Contract for deterministic research data.

    Real AkShare, Tushare, exchange, or announcement providers should implement
    this interface and keep raw collection separate from agent reasoning.
    """

    @abstractmethod
    def get_stock_profile(self, symbol: str) -> StockProfile:
        raise NotImplementedError

    @abstractmethod
    def get_daily_prices(self, symbol: str, analysis_date: str, lookback_days: int) -> list[DailyPrice]:
        raise NotImplementedError

    @abstractmethod
    def get_fundamentals(self, symbol: str, analysis_date: str | None = None) -> FundamentalSnapshot:
        raise NotImplementedError

    @abstractmethod
    def get_money_flow(self, symbol: str, analysis_date: str) -> MoneyFlowSnapshot:
        raise NotImplementedError

    def get_capital_flow_history(self, symbol: str, analysis_date: str) -> list[CapitalFlowObservation]:
        """Return dated observations without filling unavailable dimensions with zero."""
        return []

    def get_industry_context(self, symbol: str, analysis_date: str) -> IndustryContext:
        """Return typed industry-wide observations without inferring missing facts."""
        profile = self.get_stock_profile(symbol)
        return IndustryContext(
            data_status="unavailable",
            industry=profile.industry,
            as_of=analysis_date,
            unavailable_reasons=["Provider does not supply industry prosperity observations."],
        )

    def get_dragon_tiger_history(self, symbol: str, analysis_date: str) -> list[DragonTigerSeatRecord]:
        """Return disclosed seat-level history; never infer undisclosed identities."""
        return []

    @abstractmethod
    def get_announcements(self, symbol: str, analysis_date: str) -> list[Announcement]:
        raise NotImplementedError

    @abstractmethod
    def get_market_context(self, analysis_date: str) -> MarketContext:
        raise NotImplementedError

    def get_ah_premium(self, symbol: str, analysis_date: str) -> AhPremiumSnapshot:
        """Return the provider-published, date-aligned A/H comparison when applicable."""
        return AhPremiumSnapshot(
            data_status="unavailable",
            trade_date=analysis_date,
            a_symbol=symbol,
            unavailable_reasons=["Provider does not supply a date-aligned A/H comparison."],
        )

    @abstractmethod
    def get_evidence_sources(self, symbol: str, analysis_date: str) -> list[EvidenceSource]:
        raise NotImplementedError

    def get_market_signals(self, symbol: str, analysis_date: str) -> AshareMarketSignals:
        """Return optional A-share short-term and event-risk records.

        Providers must state `unavailable` rather than manufacturing a neutral
        record when their source, entitlement, or time alignment is missing.
        """
        return AshareMarketSignals(
            data_status="unavailable",
            unavailable_reasons=["Provider does not supply extended A-share market signals."],
        )

    def get_intraday_snapshot(self, symbol: str, analysis_date: str) -> IntradaySnapshot:
        """Return current-session bars/order book, or explicit unavailability.

        Providers must not relabel today's live snapshot as a historical date.
        """
        return IntradaySnapshot(
            data_status="unavailable",
            as_of=analysis_date,
            unavailable_reasons=["Provider does not supply timestamped intraday data."],
        )

    def get_convertible_bond_snapshot(self, symbol: str, analysis_date: str) -> ConvertibleBondSnapshot | None:
        """Return a dated convertible-bond snapshot when the provider supports it."""
        return None
