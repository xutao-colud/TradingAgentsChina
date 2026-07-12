from __future__ import annotations

from abc import ABC, abstractmethod

from app.schemas.report import (
    Announcement,
    DailyPrice,
    EvidenceSource,
    FundamentalSnapshot,
    MarketContext,
    MoneyFlowSnapshot,
    StockProfile,
)


class MarketDataProvider(ABC):
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
    def get_fundamentals(self, symbol: str) -> FundamentalSnapshot:
        raise NotImplementedError

    @abstractmethod
    def get_money_flow(self, symbol: str, analysis_date: str) -> MoneyFlowSnapshot:
        raise NotImplementedError

    @abstractmethod
    def get_announcements(self, symbol: str, analysis_date: str) -> list[Announcement]:
        raise NotImplementedError

    @abstractmethod
    def get_market_context(self, analysis_date: str) -> MarketContext:
        raise NotImplementedError

    @abstractmethod
    def get_evidence_sources(self, symbol: str, analysis_date: str) -> list[EvidenceSource]:
        raise NotImplementedError
