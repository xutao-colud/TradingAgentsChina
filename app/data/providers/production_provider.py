from __future__ import annotations

from dataclasses import replace

from app.data.providers.akshare_provider import AkshareSupplementProvider
from app.data.providers.base import MarketDataProvider, ProviderCapabilities
from app.data.providers.tushare_provider import TushareMarketDataProvider
from app.data.raw_snapshots import LocalRawSnapshotStore, RawDataSnapshot
from app.schemas.report import (
    AhPremiumSnapshot,
    Announcement,
    AshareMarketSignals,
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


class ProductionMarketDataProvider(MarketDataProvider):
    """Real-source composition with explicit unavailability; never sample fallback."""

    def __init__(
        self,
        tushare: TushareMarketDataProvider | None = None,
        akshare: AkshareSupplementProvider | None = None,
    ) -> None:
        raw_store = LocalRawSnapshotStore.from_runtime()
        self.tushare = tushare or TushareMarketDataProvider(raw_store=raw_store)
        self.akshare = akshare or AkshareSupplementProvider(raw_store=raw_store)
        self._signal_cache: dict[tuple[str, str], AshareMarketSignals] = {}
        self._evidence: dict[tuple[str, str], list[EvidenceSource]] = {}
        self._price_source: dict[tuple[str, str], str] = {}

    def get_stock_profile(self, symbol: str) -> StockProfile:
        return self.tushare.get_stock_profile(symbol)

    def get_daily_prices(self, symbol: str, analysis_date: str, lookback_days: int) -> list[DailyPrice]:
        prices = self.tushare.get_daily_prices(symbol, analysis_date, lookback_days)
        if prices:
            self._price_source[(symbol, analysis_date)] = "tushare"
            return prices
        prices = self.akshare.get_daily_prices(symbol, analysis_date, lookback_days)
        if prices:
            self._price_source[(symbol, analysis_date)] = "akshare"
            quality = next(
                (
                    item
                    for item in self.akshare.get_data_quality_reports(symbol, analysis_date)
                    if item.dataset == "daily_prices"
                ),
                None,
            )
            self._append_evidence(symbol, analysis_date, EvidenceSource(
                "price-001",
                f"{symbol} AkShare 日线",
                "akshare_stock_zh_a_hist",
                prices[-1].trade_date,
                snapshot_ids=quality.snapshot_ids if quality else [],
            ))
        return prices

    def get_fundamentals(self, symbol: str, analysis_date: str | None = None) -> FundamentalSnapshot:
        return self.tushare.get_fundamentals(symbol, analysis_date)

    def get_industry_context(self, symbol: str, analysis_date: str) -> IndustryContext:
        return self.tushare.get_industry_context(symbol, analysis_date)

    def get_money_flow(self, symbol: str, analysis_date: str) -> MoneyFlowSnapshot:
        flow = self.tushare.get_money_flow(symbol, analysis_date)
        northbound = self.get_market_signals(symbol, analysis_date).northbound_holding
        if not northbound or northbound.holding_change is None:
            return flow
        northbound_signal = "北向持股增加" if northbound.holding_change > 0 else "北向持股减少" if northbound.holding_change < 0 else "北向持股持平"
        return MoneyFlowSnapshot(
            flow.main_net_inflow, flow.super_large_net_inflow, flow.margin_balance_change, northbound_signal,
            flow.turnover_rate, flow.block_trade_signal, flow.large_net_inflow, flow.medium_net_inflow,
            flow.small_net_inflow, flow.as_of, flow.northbound_net_inflow,
        )

    def get_capital_flow_history(self, symbol: str, analysis_date: str) -> list[CapitalFlowObservation]:
        return self.tushare.get_capital_flow_history(symbol, analysis_date)

    def get_dragon_tiger_history(self, symbol: str, analysis_date: str) -> list[DragonTigerSeatRecord]:
        return self.tushare.get_dragon_tiger_history(symbol, analysis_date)

    def get_announcements(self, symbol: str, analysis_date: str) -> list[Announcement]:
        items = [
            *self.tushare.get_announcements(symbol, analysis_date),
            *self.akshare.get_announcements(symbol, analysis_date),
        ]
        deduplicated = {
            (item.published_at, item.title): item
            for item in items
            if item.published_at <= analysis_date
        }
        return sorted(deduplicated.values(), key=lambda item: (item.published_at, item.title))

    def get_market_context(self, analysis_date: str) -> MarketContext:
        context = self.tushare.get_market_context(analysis_date)
        if context.data_status == "verified":
            return context
        return self.akshare.get_market_context(analysis_date)

    def get_ah_premium(self, symbol: str, analysis_date: str) -> AhPremiumSnapshot:
        return self.tushare.get_ah_premium(symbol, analysis_date)

    def get_intraday_snapshot(self, symbol: str, analysis_date: str) -> IntradaySnapshot:
        snapshot = self.akshare.get_intraday_snapshot(symbol, analysis_date)
        if snapshot.data_status != "unavailable":
            for source_id in snapshot.source_ids:
                source_type = "akshare_stock_zh_a_hist_min_em" if "bars" in source_id else "akshare_stock_bid_ask_em"
                self._append_evidence(symbol, analysis_date, EvidenceSource(source_id, f"{symbol} intraday observation", source_type, snapshot.as_of))
        return snapshot

    def get_convertible_bond_snapshot(self, symbol: str, analysis_date: str) -> ConvertibleBondSnapshot:
        return self.tushare.get_convertible_bond_snapshot(symbol, analysis_date)

    def get_provider_capabilities(self) -> list[ProviderCapabilities]:
        return [*self.tushare.get_provider_capabilities(), *self.akshare.get_provider_capabilities()]

    def get_raw_snapshots(self, symbol: str, analysis_date: str) -> list[RawDataSnapshot]:
        by_id = {
            item.snapshot_id: item
            for item in [
                *self.tushare.get_raw_snapshots(symbol, analysis_date),
                *self.akshare.get_raw_snapshots(symbol, analysis_date),
            ]
        }
        return list(by_id.values())

    def get_data_quality_reports(self, symbol: str, analysis_date: str) -> list[DataQualityReport]:
        reports = [
            *self.tushare.get_data_quality_reports(symbol, analysis_date),
            *self.akshare.get_data_quality_reports(symbol, analysis_date),
        ]
        selected_price_source = self._price_source.get((symbol, analysis_date))
        if selected_price_source:
            reports = [
                replace(item, blocking=False)
                if item.dataset == "daily_prices" and item.provider != selected_price_source
                else item
                for item in reports
            ]
        by_key = {
            (item.provider, item.dataset, tuple(item.snapshot_ids)): item
            for item in reports
        }
        return list(by_key.values())

    def get_market_signals(self, symbol: str, analysis_date: str) -> AshareMarketSignals:
        cache_key = (symbol, analysis_date)
        if cache_key in self._signal_cache:
            return self._signal_cache[cache_key]
        tushare = self.tushare.get_market_signals(symbol, analysis_date)
        akshare = self.akshare.get_market_signals(symbol, analysis_date)
        supplement_sources = [
            source
            for source in akshare.evidence_sources
            if source.id != "northbound-akshare-001" or tushare.northbound_holding is None
        ]
        sources = _deduplicate_sources([*tushare.evidence_sources, *supplement_sources])
        signals = AshareMarketSignals(
            "verified" if tushare.data_status == "verified" or akshare.data_status == "verified" else "unavailable",
            dragon_tiger=tushare.dragon_tiger,
            margin_financing=tushare.margin_financing,
            northbound_holding=tushare.northbound_holding or akshare.northbound_holding,
            corporate_events=[*tushare.corporate_events, *akshare.corporate_events],
            evidence_sources=sources,
            unavailable_reasons=[*tushare.unavailable_reasons, *akshare.unavailable_reasons],
            quality_reports=[*tushare.quality_reports, *akshare.quality_reports],
        )
        self._signal_cache[cache_key] = signals
        self._evidence[cache_key] = _deduplicate_sources([
            *self._evidence.get(cache_key, []),
            *sources,
        ])
        return signals

    def get_evidence_sources(self, symbol: str, analysis_date: str) -> list[EvidenceSource]:
        signals = self.get_market_signals(symbol, analysis_date)
        return _deduplicate_sources([
            *self.tushare.get_evidence_sources(symbol, analysis_date),
            *self.akshare.get_evidence_sources(symbol, analysis_date),
            *self._evidence.get((symbol, analysis_date), []),
            *signals.evidence_sources,
        ])

    def _append_evidence(self, symbol: str, analysis_date: str, source: EvidenceSource) -> None:
        key = (symbol, analysis_date)
        self._evidence.setdefault(key, []).append(source)


def _deduplicate_sources(items: list[EvidenceSource]) -> list[EvidenceSource]:
    deduplicated: dict[str, EvidenceSource] = {}
    for item in items:
        deduplicated[item.id] = item
    return list(deduplicated.values())
