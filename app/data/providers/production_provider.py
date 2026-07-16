from __future__ import annotations

from dataclasses import replace
from datetime import date

from app.config.runtime import load_runtime_settings
from app.data.providers.akshare_provider import AkshareSupplementProvider
from app.data.providers.base import MarketDataProvider, ProviderCapabilities
from app.data.providers.tushare_provider import TushareMarketDataProvider
from app.data.providers.public_fallback_provider import PublicFallbackMarketDataProvider
from app.data.raw_snapshots import LocalRawSnapshotStore, RawDataSnapshot
from app.data.verified_cache import NullVerifiedDatasetCache, VerifiedDatasetCache
from app.data.provider_health import ProviderCircuitBreaker
from app.market.stock_snapshot import EastmoneyStockSnapshotClient
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
    MarketSentimentObservation,
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
        public_fallback: PublicFallbackMarketDataProvider | None = None,
        eastmoney_flow_client: EastmoneyStockSnapshotClient | None = None,
        verified_cache: VerifiedDatasetCache | None = None,
        circuit_breaker: ProviderCircuitBreaker | None = None,
    ) -> None:
        raw_store = LocalRawSnapshotStore.from_runtime()
        self.tushare = tushare or TushareMarketDataProvider(raw_store=raw_store)
        self.akshare = akshare or AkshareSupplementProvider(raw_store=raw_store)
        injected_provider = tushare is not None or akshare is not None or public_fallback is not None
        self.public_fallback = public_fallback or PublicFallbackMarketDataProvider(raw_store=raw_store)
        self.eastmoney_flow_client = (
            eastmoney_flow_client
            if eastmoney_flow_client is not None
            else None if injected_provider else EastmoneyStockSnapshotClient()
        )
        self.verified_cache = verified_cache or (NullVerifiedDatasetCache() if injected_provider else VerifiedDatasetCache())
        self.circuit_breaker = circuit_breaker or ProviderCircuitBreaker()
        self._signal_cache: dict[tuple[str, str], AshareMarketSignals] = {}
        self._evidence: dict[tuple[str, str], list[EvidenceSource]] = {}
        self._price_source: dict[tuple[str, str], str] = {}
        self._selected_sources: dict[tuple[str, str, str], str] = {}

    def get_stock_profile(self, symbol: str) -> StockProfile:
        normalized = _normalized(symbol)
        if self.tushare.configured:
            profile = self.tushare.get_stock_profile(normalized)
            if profile.name != normalized:
                return profile
        return self.public_fallback.get_stock_profile(normalized)

    def get_daily_prices(self, symbol: str, analysis_date: str, lookback_days: int) -> list[DailyPrice]:
        normalized = _normalized(symbol)
        prices = self.tushare.get_daily_prices(normalized, analysis_date, lookback_days) if self.tushare.configured else []
        if _usable_prices(prices):
            self._price_source[(symbol, analysis_date)] = "tushare"
            self._select("daily_prices", normalized, analysis_date, "tushare")
            self._cache_prices(normalized, analysis_date, prices, "tushare_daily")
            return prices
        cached_prices = self._fresh_cached_prices(normalized, analysis_date, lookback_days)
        if cached_prices is not None:
            return cached_prices
        prices = self.akshare.get_daily_prices(normalized, analysis_date, lookback_days) if self.circuit_breaker.allows("akshare", "daily_prices") else []
        self.circuit_breaker.record("akshare", "daily_prices", succeeded=_usable_prices(prices))
        if _usable_prices(prices):
            self._price_source[(symbol, analysis_date)] = "akshare"
            self._select("daily_prices", normalized, analysis_date, "akshare")
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
            self._cache_prices(normalized, analysis_date, prices, "akshare_stock_zh_a_hist")
            return prices
        prices = self.public_fallback.get_daily_prices(normalized, analysis_date, lookback_days) if self.circuit_breaker.allows("tencent", "daily_prices") else []
        self.circuit_breaker.record("tencent", "daily_prices", succeeded=_usable_prices(prices))
        if _usable_prices(prices):
            self._price_source[(symbol, analysis_date)] = "tencent"
            self._select("daily_prices", normalized, analysis_date, "tencent")
            self._evidence[(normalized, analysis_date)] = _deduplicate_sources([
                *self._evidence.get((normalized, analysis_date), []),
                *self.public_fallback.get_evidence_sources(normalized, analysis_date),
            ])
            self._cache_prices(normalized, analysis_date, prices, "tencent_ifzq_kline")
            return prices
        cached = self.verified_cache.load_list(
            "daily_prices", f"{normalized}-{analysis_date}", lambda row: DailyPrice(**row)
        )
        if cached and _usable_prices(cached[0]):
            prices, metadata = cached
            self._price_source[(symbol, analysis_date)] = "verified_cache"
            self._select("daily_prices", normalized, analysis_date, "verified_cache")
            self._append_evidence(normalized, analysis_date, EvidenceSource(
                "price-001", f"{normalized} 最近已核验日线快照",
                f"verified_cache:{metadata['source_type']}", metadata["as_of"],
                snapshot_ids=[metadata["sha256"]],
            ))
            return prices[-lookback_days:]
        return []

    def get_fundamentals(self, symbol: str, analysis_date: str | None = None) -> FundamentalSnapshot:
        normalized = _normalized(symbol)
        effective_date = analysis_date or date.today().isoformat()
        if self.tushare.configured:
            snapshot = self.tushare.get_fundamentals(normalized, effective_date)
            if snapshot.statement_as_of:
                self._select("fundamentals", normalized, effective_date, "tushare")
                self.verified_cache.save("fundamentals", f"{normalized}-{effective_date}", snapshot, source_type="tushare_fina_indicator", as_of=snapshot.statement_as_of)
                return snapshot
        cached = self.verified_cache.load("fundamentals", f"{normalized}-{effective_date}", lambda row: FundamentalSnapshot(**row))
        if (
            cached
            and self.verified_cache.is_fresh("fundamentals", cached[1])
            and _fundamental_cache_complete(cached[0])
        ):
            snapshot, metadata = cached
            self._select("fundamentals", normalized, effective_date, "verified_cache")
            self._append_evidence(normalized, effective_date, EvidenceSource(
                "fund-001", f"{normalized} 最近已核验财务快照", f"verified_cache:{metadata['source_type']}", metadata["as_of"], snapshot_ids=[metadata["sha256"]],
            ))
            return snapshot
        snapshot = self.public_fallback.get_fundamentals(normalized, effective_date)
        if snapshot.statement_as_of:
            self._select("fundamentals", normalized, effective_date, "sina")
            self._evidence[(normalized, effective_date)] = _deduplicate_sources([
                *self._evidence.get((normalized, effective_date), []),
                *self.public_fallback.get_evidence_sources(normalized, effective_date),
            ])
            self.verified_cache.save("fundamentals", f"{normalized}-{effective_date}", snapshot, source_type="sina_financial_abstract", as_of=snapshot.statement_as_of)
            return snapshot
        cached = self.verified_cache.load("fundamentals", f"{normalized}-{effective_date}", lambda row: FundamentalSnapshot(**row))
        if cached:
            snapshot, metadata = cached
            self._select("fundamentals", normalized, effective_date, "verified_cache")
            self._append_evidence(normalized, effective_date, EvidenceSource(
                "fund-001", f"{normalized} 最近已核验财务快照", f"verified_cache:{metadata['source_type']}", metadata["as_of"], snapshot_ids=[metadata["sha256"]],
            ))
            return snapshot
        return snapshot

    def get_industry_context(self, symbol: str, analysis_date: str) -> IndustryContext:
        if self.tushare.configured:
            return self.tushare.get_industry_context(symbol, analysis_date)
        profile = self.get_stock_profile(symbol)
        return IndustryContext("unavailable", profile.industry, analysis_date, unavailable_reasons=["Tushare 未配置，行业景气数据不可用。"])

    def get_industry_flow_ranking(
        self,
        reference_date: str,
        calendar_lookback_days: int,
    ) -> tuple[str, list[IndustryFlowObservation]]:
        return self.tushare.get_industry_flow_ranking(reference_date, calendar_lookback_days) if self.tushare.configured else (reference_date, [])

    def get_money_flow(self, symbol: str, analysis_date: str) -> MoneyFlowSnapshot:
        normalized = _normalized(symbol)
        flow = self.tushare.get_money_flow(normalized, analysis_date) if self.tushare.configured else MoneyFlowSnapshot(None, None, None, "数据不足", None, "数据不足")
        if flow.main_net_inflow is None:
            fresh_cached = self.verified_cache.load("money_flow", f"{normalized}-{analysis_date}", lambda row: MoneyFlowSnapshot(**row))
            if fresh_cached and self.verified_cache.is_fresh("money_flow", fresh_cached[1]):
                flow, metadata = fresh_cached
                self._select("money_flow", normalized, analysis_date, "verified_cache")
                self._append_evidence(normalized, analysis_date, EvidenceSource(
                    "flow-001", f"{normalized} 最近已核验资金流快照", f"verified_cache:{metadata['source_type']}", metadata["as_of"], snapshot_ids=[metadata["sha256"]],
                ))
                return flow
            public_flow = self.public_fallback.get_money_flow(normalized, analysis_date) if self.circuit_breaker.allows("ths", "money_flow") else MoneyFlowSnapshot(None, None, None, "数据不足", None, "数据不足")
            public_source = _flow_source_type(
                self.public_fallback.get_evidence_sources(normalized, analysis_date)
            )
            self.circuit_breaker.record(
                "ths", "money_flow", succeeded=public_source == "ths_individual_fund_flow"
            )
            self.circuit_breaker.record(
                "sina_tick", "money_flow", succeeded=public_source == "sina_tick_trade_direction"
            )
            if _usable_flow(public_flow):
                flow = public_flow
                selected_source = "sina_tick" if public_source == "sina_tick_trade_direction" else "ths"
                self._select("money_flow", normalized, analysis_date, selected_source)
                self._evidence[(normalized, analysis_date)] = _deduplicate_sources([
                    *self._evidence.get((normalized, analysis_date), []),
                    *self.public_fallback.get_evidence_sources(normalized, analysis_date),
                ])
                self.verified_cache.save(
                    "money_flow", f"{normalized}-{analysis_date}", flow,
                    source_type=public_source or "public_money_flow",
                    as_of=flow.as_of or analysis_date,
                )
            else:
                eastmoney_flow = self._get_eastmoney_flow(normalized, analysis_date)
                if _usable_flow(eastmoney_flow):
                    return eastmoney_flow
                cached = self.verified_cache.load("money_flow", f"{normalized}-{analysis_date}", lambda row: MoneyFlowSnapshot(**row))
                if cached:
                    flow, metadata = cached
                    self._select("money_flow", normalized, analysis_date, "verified_cache")
                    self._append_evidence(normalized, analysis_date, EvidenceSource(
                        "flow-001", f"{normalized} 最近已核验资金流快照", f"verified_cache:{metadata['source_type']}", metadata["as_of"], snapshot_ids=[metadata["sha256"]],
                    ))
        else:
            self._select("money_flow", normalized, analysis_date, "tushare")
            self.verified_cache.save("money_flow", f"{normalized}-{analysis_date}", flow, source_type="tushare_moneyflow", as_of=flow.as_of or analysis_date)
        northbound = self.get_market_signals(symbol, analysis_date).northbound_holding
        if not northbound or northbound.holding_change is None:
            return flow
        northbound_signal = "北向持股增加" if northbound.holding_change > 0 else "北向持股减少" if northbound.holding_change < 0 else "北向持股持平"
        return MoneyFlowSnapshot(
            flow.main_net_inflow, flow.super_large_net_inflow, flow.margin_balance_change, northbound_signal,
            flow.turnover_rate, flow.block_trade_signal, flow.large_net_inflow, flow.medium_net_inflow,
            flow.small_net_inflow, flow.as_of, flow.northbound_net_inflow,
            flow.trade_direction_net_inflow, flow.trade_direction_gross_amount, flow.flow_method,
        )

    def get_capital_flow_history(self, symbol: str, analysis_date: str) -> list[CapitalFlowObservation]:
        return self.tushare.get_capital_flow_history(symbol, analysis_date) if self.tushare.configured else []

    def get_dragon_tiger_history(self, symbol: str, analysis_date: str) -> list[DragonTigerSeatRecord]:
        return self.tushare.get_dragon_tiger_history(symbol, analysis_date) if self.tushare.configured else []

    def get_announcements(self, symbol: str, analysis_date: str) -> list[Announcement]:
        items = [
            *(self.tushare.get_announcements(symbol, analysis_date) if self.tushare.configured else []),
            *self.akshare.get_announcements(symbol, analysis_date),
        ]
        deduplicated = {
            (item.published_at, item.title): item
            for item in items
            if item.published_at <= analysis_date
        }
        return sorted(deduplicated.values(), key=lambda item: (item.published_at, item.title))

    def get_market_context(self, analysis_date: str) -> MarketContext:
        context = self.tushare.get_market_context(analysis_date) if self.tushare.configured else _unavailable_market(analysis_date)
        if context.data_status == "verified":
            self._selected_sources[("__market__", analysis_date, "market_context")] = "tushare"
            self.verified_cache.save("market_context", analysis_date, context, source_type="tushare_market_context", as_of=context.as_of or analysis_date)
            return context
        fresh_cached = self.verified_cache.load("market_context", analysis_date, _market_context_from_dict)
        if fresh_cached and self.verified_cache.is_fresh("market_context", fresh_cached[1]):
            context, metadata = fresh_cached
            self._selected_sources[("__market__", analysis_date, "market_context")] = "verified_cache"
            self._append_evidence("__market__", analysis_date, EvidenceSource(
                "market-001", "最近已核验市场宽度快照", f"verified_cache:{metadata['source_type']}", metadata["as_of"], snapshot_ids=[metadata["sha256"]],
            ))
            return context
        context = self.public_fallback.get_market_context(analysis_date) if self.circuit_breaker.allows("sina", "market_context") else _unavailable_market(analysis_date)
        self.circuit_breaker.record("sina", "market_context", succeeded=context.data_status == "verified")
        if context.data_status == "verified":
            self._selected_sources[("__market__", analysis_date, "market_context")] = "sina"
            self._evidence[("__market__", analysis_date)] = self.public_fallback.get_evidence_sources("__market__", analysis_date)
            self.verified_cache.save("market_context", analysis_date, context, source_type="sina_market_center+tencent_index", as_of=context.as_of or analysis_date)
            return context
        context = self.akshare.get_market_context(analysis_date) if self.circuit_breaker.allows("akshare", "market_context") else _unavailable_market(analysis_date)
        self.circuit_breaker.record("akshare", "market_context", succeeded=context.data_status == "verified")
        if context.data_status == "verified":
            self._selected_sources[("__market__", analysis_date, "market_context")] = "akshare"
            self.verified_cache.save("market_context", analysis_date, context, source_type="akshare_market_context", as_of=context.as_of or analysis_date)
            return context
        cached = self.verified_cache.load("market_context", analysis_date, _market_context_from_dict)
        if cached:
            context, metadata = cached
            self._selected_sources[("__market__", analysis_date, "market_context")] = "verified_cache"
            self._append_evidence("__market__", analysis_date, EvidenceSource(
                "market-001", "最近已核验市场宽度快照", f"verified_cache:{metadata['source_type']}", metadata["as_of"], snapshot_ids=[metadata["sha256"]],
            ))
            return context
        return context

    def get_ah_premium(self, symbol: str, analysis_date: str) -> AhPremiumSnapshot:
        return self.tushare.get_ah_premium(symbol, analysis_date) if self.tushare.configured else AhPremiumSnapshot("unavailable", analysis_date, _normalized(symbol))

    def get_intraday_snapshot(self, symbol: str, analysis_date: str) -> IntradaySnapshot:
        snapshot = self.akshare.get_intraday_snapshot(symbol, analysis_date)
        if snapshot.data_status != "unavailable":
            for source_id in snapshot.source_ids:
                source_type = "akshare_stock_zh_a_hist_min_em" if "bars" in source_id else "akshare_stock_bid_ask_em"
                self._append_evidence(symbol, analysis_date, EvidenceSource(source_id, f"{symbol} intraday observation", source_type, snapshot.as_of))
        return snapshot

    def get_convertible_bond_snapshot(self, symbol: str, analysis_date: str) -> ConvertibleBondSnapshot:
        return self.tushare.get_convertible_bond_snapshot(symbol, analysis_date) if self.tushare.configured else None

    def get_provider_capabilities(self) -> list[ProviderCapabilities]:
        return [*self.tushare.get_provider_capabilities(), *self.akshare.get_provider_capabilities(), *self.public_fallback.get_provider_capabilities()]

    def get_raw_snapshots(self, symbol: str, analysis_date: str) -> list[RawDataSnapshot]:
        by_id = {
            item.snapshot_id: item
            for item in [
                *self.tushare.get_raw_snapshots(symbol, analysis_date),
                *self.akshare.get_raw_snapshots(symbol, analysis_date),
                *self.public_fallback.get_raw_snapshots(symbol, analysis_date),
            ]
        }
        return list(by_id.values())

    def get_data_quality_reports(self, symbol: str, analysis_date: str) -> list[DataQualityReport]:
        reports = [
            *self.tushare.get_data_quality_reports(symbol, analysis_date),
            *self.akshare.get_data_quality_reports(symbol, analysis_date),
            *self.public_fallback.get_data_quality_reports(symbol, analysis_date),
        ]
        selected_price_source = self._price_source.get((symbol, analysis_date))
        if selected_price_source:
            reports = [
                replace(item, blocking=False)
                if item.dataset == "daily_prices" and item.provider != selected_price_source
                else item
                for item in reports
            ]
        selected = {
            dataset: source for (selected_symbol, selected_date, dataset), source in self._selected_sources.items()
            if selected_symbol in {_normalized(symbol), "__market__"} and selected_date == analysis_date
        }
        reports = [
            replace(item, blocking=False)
            if item.status == "failed" and _dataset_was_recovered(item.dataset, selected)
            else item
            for item in reports
        ]
        by_key = {(item.provider, item.dataset, item.status): item for item in reports}
        return list(by_key.values())

    def get_market_signals(self, symbol: str, analysis_date: str) -> AshareMarketSignals:
        cache_key = (symbol, analysis_date)
        if cache_key in self._signal_cache:
            return self._signal_cache[cache_key]
        tushare = self.tushare.get_market_signals(symbol, analysis_date) if self.tushare.configured else AshareMarketSignals("unavailable", unavailable_reasons=["Tushare 未配置。"])
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
            *self.public_fallback.get_evidence_sources(symbol, analysis_date),
            *self._evidence.get((symbol, analysis_date), []),
            *self._evidence.get((_normalized(symbol), analysis_date), []),
            *self._evidence.get(("__market__", analysis_date), []),
            *signals.evidence_sources,
        ])

    def _get_eastmoney_flow(self, symbol: str, analysis_date: str) -> MoneyFlowSnapshot:
        unavailable = MoneyFlowSnapshot(None, None, None, "数据不足", None, "数据不足")
        if (
            self.eastmoney_flow_client is None
            or not self.circuit_breaker.allows("eastmoney", "money_flow")
        ):
            return unavailable
        try:
            breakdown = self.eastmoney_flow_client.fetch_money_flow(symbol)
        except Exception:
            breakdown = None
        succeeded = bool(breakdown and breakdown.main_net_inflow is not None)
        self.circuit_breaker.record("eastmoney", "money_flow", succeeded=succeeded)
        if not succeeded or breakdown is None:
            return unavailable
        flow = MoneyFlowSnapshot(
            main_net_inflow=breakdown.main_net_inflow,
            super_large_net_inflow=breakdown.super_large_net_inflow,
            margin_balance_change=None,
            northbound_signal="数据不足",
            turnover_rate=None,
            block_trade_signal="数据不足",
            large_net_inflow=breakdown.large_net_inflow,
            medium_net_inflow=breakdown.medium_net_inflow,
            small_net_inflow=breakdown.small_net_inflow,
            as_of=breakdown.trade_date,
            flow_method="vendor_order_size_flow",
        )
        self._select("money_flow", symbol, analysis_date, "eastmoney")
        self._append_evidence(symbol, analysis_date, EvidenceSource(
            "flow-001", f"{symbol} 东方财富分档资金流", "eastmoney_push2his",
            breakdown.trade_date or analysis_date,
        ))
        self.verified_cache.save(
            "money_flow", f"{symbol}-{analysis_date}", flow,
            source_type="eastmoney_push2his", as_of=breakdown.trade_date or analysis_date,
        )
        return flow

    def _append_evidence(self, symbol: str, analysis_date: str, source: EvidenceSource) -> None:
        key = (symbol, analysis_date)
        self._evidence.setdefault(key, []).append(source)

    def _select(self, dataset: str, symbol: str, analysis_date: str, source: str) -> None:
        self._selected_sources[(symbol, analysis_date, dataset)] = source

    def _cache_prices(self, symbol: str, analysis_date: str, prices: list[DailyPrice], source_type: str) -> None:
        self.verified_cache.save("daily_prices", f"{symbol}-{analysis_date}", prices, source_type=source_type, as_of=prices[-1].trade_date)

    def _fresh_cached_prices(self, symbol: str, analysis_date: str, lookback_days: int) -> list[DailyPrice] | None:
        cached = self.verified_cache.load_list("daily_prices", f"{symbol}-{analysis_date}", lambda row: DailyPrice(**row))
        if not cached or not self.verified_cache.is_fresh("daily_prices", cached[1]) or not _usable_prices(cached[0]):
            return None
        prices, metadata = cached
        self._price_source[(symbol, analysis_date)] = "verified_cache"
        self._select("daily_prices", symbol, analysis_date, "verified_cache")
        self._append_evidence(symbol, analysis_date, EvidenceSource(
            "price-001", f"{symbol} 最近已核验日线快照", f"verified_cache:{metadata['source_type']}", metadata["as_of"], snapshot_ids=[metadata["sha256"]],
        ))
        return prices[-lookback_days:]


def _deduplicate_sources(items: list[EvidenceSource]) -> list[EvidenceSource]:
    deduplicated: dict[str, EvidenceSource] = {}
    for item in items:
        deduplicated[item.id] = item
    return list(deduplicated.values())


def _normalized(symbol: str) -> str:
    from app.rules.trading_rules import normalize_symbol
    return normalize_symbol(symbol)


def _usable_prices(prices: list[DailyPrice]) -> bool:
    return bool(prices) and all(item.close > 0 and item.volume >= 0 for item in prices)


def _usable_flow(flow: MoneyFlowSnapshot) -> bool:
    return flow.as_of is not None and any(
        value is not None
        for value in (
            flow.main_net_inflow,
            flow.super_large_net_inflow,
            flow.trade_direction_net_inflow,
        )
    )


def _flow_source_type(sources: list[EvidenceSource]) -> str | None:
    return next((item.source_type for item in sources if item.id == "flow-001"), None)


def _dataset_was_recovered(dataset: str, selected: dict[str, str]) -> bool:
    if dataset == "daily_prices":
        return "daily_prices" in selected
    if dataset in {"market_sentiment", "market_breadth_current", "market_breadth_public"}:
        return "market_context" in selected
    return False


def _unavailable_market(analysis_date: str) -> MarketContext:
    return MarketContext("上证指数", None, None, None, None, None, None, "数据不足", [], data_status="unavailable", as_of=None)


def _market_context_from_dict(row: dict[str, object]) -> MarketContext:
    values = dict(row)
    history = values.get("sentiment_history", [])
    values["sentiment_history"] = [
        item if isinstance(item, MarketSentimentObservation) else MarketSentimentObservation(**item)
        for item in history if isinstance(item, (dict, MarketSentimentObservation))
    ]
    return MarketContext(**values)


def _fundamental_cache_complete(snapshot: FundamentalSnapshot) -> bool:
    required = load_runtime_settings().get("providers", "public_fallback", "fundamental_quality_fields")
    return all(getattr(snapshot, field, None) is not None for field in required)
