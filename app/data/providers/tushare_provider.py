from __future__ import annotations

import os
import math
import hashlib
from statistics import median
from dataclasses import replace
from datetime import date, timedelta
from typing import Any, Protocol

from app.config.runtime import load_runtime_settings
from app.data.providers.base import MarketDataProvider, ProviderCapabilities
from app.data.quality import validate_dataset_records, validate_raw_snapshot
from app.data.raw_snapshots import (
    InMemoryRawSnapshotStore,
    LocalRawSnapshotStore,
    RawDataSnapshot,
    RawSnapshotStore,
    build_raw_snapshot,
    snapshot_matches,
)
from app.rules.trading_rules import infer_board, normalize_symbol
from app.rules.special_instruments import ConvertibleBondSnapshot
from app.schemas.report import (
    AhPremiumSnapshot,
    Announcement,
    AshareMarketSignals,
    CapitalFlowObservation,
    CorporateEvent,
    DailyPrice,
    DataQualityIssue,
    DataQualityReport,
    DragonTigerRecord,
    DragonTigerSeatRecord,
    EvidenceSource,
    FundamentalSnapshot,
    IndustryChainNode,
    IndustryContext,
    IndustryFlowObservation,
    IndustryValuationObservation,
    MarginFinancingRecord,
    MarketContext,
    MarketSentimentObservation,
    MoneyFlowSnapshot,
    NorthboundHoldingRecord,
    StockProfile,
)
from app.skills.sentiment_dynamics import analyze_sentiment_dynamics


class TushareClient(Protocol):
    def __getattr__(self, name: str) -> Any: ...


class TushareMarketDataProvider(MarketDataProvider):
    """Authenticated Tushare adapter with explicit provenance and no sample fallback."""

    def __init__(
        self,
        pro_client: TushareClient | None = None,
        raw_store: RawSnapshotStore | None = None,
    ) -> None:
        self.config = load_runtime_settings().get("providers", "tushare")
        self._client = pro_client or self._build_client()
        self._raw_store = raw_store or InMemoryRawSnapshotStore()
        self._raw_snapshots: list[RawDataSnapshot] = []
        self._query_outcomes: list[tuple[str, dict[str, object], str]] = []
        self._evidence: dict[str, EvidenceSource] = {}
        self._errors: list[str] = []
        self._signals: dict[tuple[str, str], AshareMarketSignals] = {}
        self._market_contexts: dict[str, MarketContext] = {}
        self._capital_flow_histories: dict[tuple[str, str], list[CapitalFlowObservation]] = {}
        self._dragon_tiger_histories: dict[tuple[str, str], list[DragonTigerSeatRecord]] = {}
        self._industry_contexts: dict[tuple[str, str], IndustryContext] = {}
        self._quality_reports: dict[tuple[str, str, str], DataQualityReport] = {}
        self._listed_universe_cache: list[dict[str, Any]] | None = None

    @property
    def configured(self) -> bool:
        return self._client is not None

    def get_provider_capabilities(self) -> list[ProviderCapabilities]:
        return [ProviderCapabilities(
            provider="tushare",
            datasets=frozenset(self.config["capabilities"]),
            persists_raw_snapshots=isinstance(self._raw_store, LocalRawSnapshotStore),
        )]

    def get_stock_profile(self, symbol: str) -> StockProfile:
        normalized = normalize_symbol(symbol)
        records = self._query("stock_basic", ts_code=normalized)
        if not records:
            return StockProfile(normalized, normalized, "未知", infer_board(normalized), is_suspended=False)
        row = records[0]
        name = _text(row, "name", default=normalized)
        self._record_evidence("profile-001", f"{normalized} Tushare 股票基础信息", "tushare_stock_basic", _text(row, "list_date", default="unknown"))
        return StockProfile(
            normalized, name, _text(row, "industry", default="未知"), infer_board(normalized),
            name.upper().startswith(("ST", "*ST")), list_date=_iso_date(_text(row, "list_date")) or None,
        )

    def get_daily_prices(self, symbol: str, analysis_date: str, lookback_days: int) -> list[DailyPrice]:
        normalized = normalize_symbol(symbol)
        start_date = (date.fromisoformat(analysis_date) - timedelta(days=max(lookback_days * 3, 90))).strftime("%Y%m%d")
        records = self._query("daily", ts_code=normalized, start_date=start_date, end_date=_compact_date(analysis_date))
        prices = [
            DailyPrice(
                trade_date=_iso_date(_text(row, "trade_date")),
                open=_number(row, "open"), high=_number(row, "high"), low=_number(row, "low"), close=_number(row, "close"),
                volume=_number(row, "vol") * 100, amount=_number(row, "amount") * 1000, turnover_rate=None,
            )
            for row in records
        ]
        basic = {_text(row, "trade_date"): row for row in self._query("daily_basic", ts_code=normalized, start_date=start_date, end_date=_compact_date(analysis_date))}
        prices = [
            DailyPrice(item.trade_date, item.open, item.high, item.low, item.close, item.volume, item.amount, _optional_number(basic.get(item.trade_date.replace("-", ""), {}), "turnover_rate"))
            for item in prices
        ]
        prices.sort(key=lambda item: item.trade_date)
        prices, quality = validate_dataset_records(
            provider="tushare",
            dataset="daily_prices",
            records=prices,
            analysis_date=analysis_date,
            snapshot_ids=self._snapshot_ids(("daily", "daily_basic"), normalized, analysis_date),
        )
        self._quality_reports[(normalized, analysis_date, "daily_prices")] = quality
        if prices:
            self._record_evidence(
                "price-001",
                f"{normalized} Tushare 日线",
                "tushare_daily",
                prices[-1].trade_date,
                quality.snapshot_ids,
            )
        return prices[-lookback_days:]

    def get_fundamentals(self, symbol: str, analysis_date: str | None = None) -> FundamentalSnapshot:
        normalized = normalize_symbol(symbol)
        effective_date = analysis_date or date.today().isoformat()
        target_snapshot_start = len(self._raw_snapshots)
        indicators = self._query("fina_indicator", ts_code=normalized)
        basic = self._query("daily_basic", ts_code=normalized, end_date=_compact_date(effective_date))
        row = _latest_available_record(indicators, effective_date)
        basic_row = _latest_available_record(basic, effective_date)
        income = _latest_available_record(self._query("income", ts_code=normalized), effective_date)
        balance = _latest_available_record(self._query("balancesheet", ts_code=normalized), effective_date)
        cashflow = _latest_available_record(self._query("cashflow", ts_code=normalized), effective_date)
        revenue = _optional_number(income, "total_revenue")
        net_income = _optional_number(income, "n_income")
        operating_cash_flow = _optional_number(cashflow, "n_cashflow_act")
        cashflow_quality = operating_cash_flow / net_income if operating_cash_flow is not None and net_income not in {None, 0} else _number(row, "ocf_yoy")
        target_snapshot_ids = [item.snapshot_id for item in self._raw_snapshots[target_snapshot_start:]]
        if row:
            self._record_evidence(
                "fund-001",
                f"{normalized} Tushare 财务指标",
                "tushare_fina_indicator",
                _iso_date(_text(row, "end_date", default="unknown")),
                target_snapshot_ids,
            )
        peer_medians, peer_sizes, peer_as_of, peer_source_id, peer_reasons = self._peer_medians(
            normalized,
            row,
            effective_date,
        )
        return FundamentalSnapshot(
            revenue_growth_yoy=_number(row, "or_yoy"), profit_growth_yoy=_number(row, "q_netprofit_yoy"), roe=_number(row, "roe"),
            gross_margin=_number(row, "grossprofit_margin"), debt_to_asset=_number(row, "debt_to_assets"), pe_ttm=_number(basic_row, "pe_ttm"),
            pb=_number(basic_row, "pb"), cashflow_quality=cashflow_quality, forecast_revision="未获取到业绩预期修正",
            revenue=revenue,
            net_income=net_income,
            operating_cash_flow=operating_cash_flow,
            total_assets=_optional_number(balance, "total_assets"),
            total_equity=_optional_number(balance, "total_hldr_eqy_exc_min_int"),
            accounts_receivable=_optional_number(balance, "accounts_receiv"),
            inventory=_optional_number(balance, "inventories"),
            statement_as_of=_iso_date(_text(income, "end_date", default="")) or None,
            peer_medians=peer_medians,
            peer_sample_sizes=peer_sizes,
            peer_as_of=peer_as_of,
            peer_source_id=peer_source_id,
            peer_unavailable_reasons=peer_reasons,
        )

    def _peer_medians(
        self,
        symbol: str,
        target_indicator: dict[str, Any],
        analysis_date: str,
    ) -> tuple[dict[str, float], dict[str, int], str | None, str | None, list[str]]:
        config = self.config["fundamental_peers"]
        if not config["enabled"]:
            return {}, {}, None, None, ["同行财务比较已由运行配置关闭。"]
        target_period = _text(target_indicator, "end_date")
        if not target_period:
            return {}, {}, None, None, ["目标公司缺少可用报告期，无法对齐同行财务样本。"]

        universe = self._listed_stock_universe()
        target_member = next((item for item in universe if _text(item, "ts_code") == symbol), {})
        if not target_member:
            target_member = _latest_record(self._query("stock_basic", ts_code=symbol))
        industry = _text(target_member, "industry")
        if not industry:
            return {}, {}, _iso_date(target_period), None, ["股票基础信息缺少行业字段，无法建立同行样本。"]

        peer_codes = sorted({
            _text(item, "ts_code")
            for item in universe
            if _text(item, "industry") == industry and _text(item, "ts_code") not in {"", symbol}
        })[:int(config["maximum_members"])]
        if not peer_codes:
            return {}, {}, _iso_date(target_period), None, [f"行业 {industry} 未取得其他上市公司样本。"]

        peer_snapshot_start = len(self._raw_snapshots)
        candidate_rows: list[dict[str, Any]] = []
        if config["batch_enabled"]:
            candidate_rows = self._query(
                "fina_indicator_vip",
                period=target_period,
                fields=config["batch_fields"],
            )
        by_symbol = {
            _text(item, "ts_code"): item
            for item in candidate_rows
            if _text(item, "ts_code") in peer_codes
            and _text(item, "end_date") == target_period
            and _record_available_on(item, analysis_date)
        }
        for peer_code in peer_codes:
            if peer_code in by_symbol:
                continue
            peer_rows = self._query("fina_indicator", ts_code=peer_code, period=target_period)
            peer_row = _latest_available_record(
                [item for item in peer_rows if _text(item, "end_date") == target_period],
                analysis_date,
            )
            if peer_row:
                by_symbol[peer_code] = peer_row

        metric_fields = config["metric_fields"]
        normalized_records: list[dict[str, Any]] = []
        for peer_code, peer_row in by_symbol.items():
            record: dict[str, Any] = {
                "ts_code": peer_code,
                "end_date": _iso_date(target_period),
            }
            record.update({metric: _optional_number(peer_row, field) for metric, field in metric_fields.items()})
            if any(record[metric] is not None for metric in metric_fields):
                normalized_records.append(record)

        peer_snapshot_ids = [item.snapshot_id for item in self._raw_snapshots[peer_snapshot_start:]]
        valid_records, quality = validate_dataset_records(
            provider="tushare",
            dataset="fundamental_peers",
            records=normalized_records,
            analysis_date=analysis_date,
            snapshot_ids=peer_snapshot_ids,
        )
        self._quality_reports[(symbol, analysis_date, "fundamental_peers")] = quality
        minimum_samples = int(load_runtime_settings().get("data_quality", "datasets", "fundamental_peers", "minimum_records"))
        medians: dict[str, float] = {}
        sample_sizes: dict[str, int] = {}
        reasons: list[str] = []
        if quality.status == "passed":
            for metric in metric_fields:
                values = [
                    float(item[metric])
                    for item in valid_records
                    if isinstance(item.get(metric), (int, float)) and math.isfinite(float(item[metric]))
                ]
                sample_sizes[metric] = len(values)
                if len(values) >= minimum_samples:
                    medians[metric] = float(median(values))
                else:
                    reasons.append(f"{metric} 仅有 {len(values)} 个有效同行样本，少于要求的 {minimum_samples} 个。")
        else:
            reasons.extend(item.message for item in quality.issues)

        source_id = "peer-fund-001" if medians else None
        if source_id:
            self._record_evidence(
                source_id,
                f"{industry} 行业同报告期财务指标中位数",
                "tushare_stock_basic_fina_indicator",
                _iso_date(target_period),
                peer_snapshot_ids,
            )
        elif not reasons:
            reasons.append("未取得通过质量校验的同行财务样本。")
        return medians, sample_sizes, _iso_date(target_period), source_id, _unique(reasons)

    def get_industry_context(self, symbol: str, analysis_date: str) -> IndustryContext:
        normalized = normalize_symbol(symbol)
        cache_key = (normalized, analysis_date)
        if cache_key in self._industry_contexts:
            return self._industry_contexts[cache_key]
        profile = self.get_stock_profile(normalized)
        config = self.config["industry_prosperity"]
        if not config["enabled"]:
            context = IndustryContext(
                data_status="unavailable",
                industry=profile.industry,
                as_of=analysis_date,
                unavailable_reasons=["行业景气数据采集已由运行配置关闭。"],
            )
            self._industry_contexts[cache_key] = context
            return context

        reasons: list[str] = []
        flow_snapshot_start = len(self._raw_snapshots)
        flow_rows = self._query("industry_moneyflow", trade_date=_compact_date(analysis_date))
        flow_snapshot_ids = [item.snapshot_id for item in self._raw_snapshots[flow_snapshot_start:]]
        flows = [
            IndustryFlowObservation(
                trade_date=_iso_date(_text(row, "trade_date")),
                industry=_text(row, "industry"),
                industry_code=_text(row, "ts_code"),
                net_amount=_number(row, "net_amount") * 100_000_000,
                pct_change=_optional_number(row, "pct_change"),
                company_count=_optional_int(row, "company_num"),
                source_id="industry-flow-001",
            )
            for row in flow_rows
            if _text(row, "trade_date") and _text(row, "industry") and _text(row, "ts_code")
        ]
        flows, flow_quality = validate_dataset_records(
            provider="tushare",
            dataset="industry_flow",
            records=flows,
            analysis_date=analysis_date,
            snapshot_ids=flow_snapshot_ids,
        )
        self._quality_reports[(normalized, analysis_date, "industry_flow")] = flow_quality
        if flows:
            self._record_evidence(
                "industry-flow-001",
                f"{analysis_date} Tushare 同花顺全行业资金流向",
                "tushare_moneyflow_ind_ths",
                analysis_date,
                flow_snapshot_ids,
            )
        else:
            reasons.extend(item.message for item in flow_quality.issues)

        target_flow = next(
            (
                item for item in flows
                if _industry_names_match(profile.industry, item.industry, config["industry_name_aliases"])
            ),
            None,
        )
        if flows and target_flow is None:
            reasons.append(f"股票行业 {profile.industry} 无法与行业资金流分类对齐。")

        valuations, valuation_snapshot_ids = self._industry_valuation_history(
            normalized,
            profile.industry,
            analysis_date,
            config,
        )
        valuations, valuation_quality = validate_dataset_records(
            provider="tushare",
            dataset="industry_valuation",
            records=valuations,
            analysis_date=analysis_date,
            snapshot_ids=valuation_snapshot_ids,
        )
        self._quality_reports[(normalized, analysis_date, "industry_valuation")] = valuation_quality
        if valuations:
            self._record_evidence(
                "industry-valuation-001",
                f"{profile.industry} 行业同行 PE/PB 历史中位数",
                "tushare_stock_basic_daily_basic",
                valuations[-1].trade_date,
                valuation_snapshot_ids,
            )
        else:
            reasons.extend(item.message for item in valuation_quality.issues)

        chain_nodes = [
            IndustryChainNode(
                stage=str(item["stage"]),
                industry=str(item["industry"]),
                source_id=str(item["source_id"]),
            )
            for item in config["chain_relations"]
            if _industry_names_match(
                profile.industry,
                str(item.get("target_industry", "")),
                config["industry_name_aliases"],
            )
        ]
        for relation in config["chain_relations"]:
            if any(node.source_id == str(relation.get("source_id")) for node in chain_nodes):
                self._record_evidence(
                    str(relation["source_id"]),
                    str(relation.get("title", f"{profile.industry} 产业链分类知识")),
                    "configured_industry_chain_knowledge",
                    str(relation["as_of"]),
                )
        if not chain_nodes:
            reasons.append(f"未配置可追溯的 {profile.industry} 产业链上下游关系。")

        source_ids = []
        if flows:
            source_ids.append("industry-flow-001")
        if valuations:
            source_ids.append("industry-valuation-001")
        source_ids.extend(node.source_id for node in chain_nodes)
        context = IndustryContext(
            data_status="verified" if target_flow is not None and flow_quality.status == "passed" else "partial",
            industry=target_flow.industry if target_flow is not None else profile.industry,
            as_of=analysis_date,
            flow_observations=list(flows),
            valuation_history=list(valuations),
            chain_nodes=chain_nodes,
            source_ids=_unique(source_ids),
            unavailable_reasons=_unique(reasons),
        )
        self._industry_contexts[cache_key] = context
        return context

    def _industry_valuation_history(
        self,
        symbol: str,
        industry: str,
        analysis_date: str,
        config: dict[str, Any],
    ) -> tuple[list[IndustryValuationObservation], list[str]]:
        universe = self._listed_stock_universe()
        peer_codes = sorted({
            _text(item, "ts_code")
            for item in universe
            if _text(item, "industry") == industry and _text(item, "ts_code")
        })[:int(config["maximum_peer_members"])]
        if symbol not in peer_codes:
            peer_codes = [symbol, *peer_codes][:int(config["maximum_peer_members"])]
        if len(peer_codes) < int(config["minimum_peer_samples"]):
            return [], []

        end_date = _compact_date(analysis_date)
        start_date = (
            date.fromisoformat(analysis_date) - timedelta(days=int(config["valuation_calendar_lookback_days"]))
        ).strftime("%Y%m%d")
        snapshot_start = len(self._raw_snapshots)
        by_date: dict[str, dict[str, list[float]]] = {}
        for peer_code in peer_codes:
            for row in self._query("daily_basic", ts_code=peer_code, start_date=start_date, end_date=end_date):
                trade_date = _iso_date(_text(row, "trade_date"))
                if not trade_date or trade_date > analysis_date:
                    continue
                bucket = by_date.setdefault(trade_date, {"pe": [], "pb": []})
                pe = _optional_number(row, "pe_ttm")
                pb = _optional_number(row, "pb")
                if pe is not None and math.isfinite(pe) and pe > 0:
                    bucket["pe"].append(pe)
                if pb is not None and math.isfinite(pb) and pb > 0:
                    bucket["pb"].append(pb)

        minimum_samples = int(config["minimum_peer_samples"])
        observations = [
            IndustryValuationObservation(
                trade_date=trade_date,
                pe_ttm_median=float(median(values["pe"])) if len(values["pe"]) >= minimum_samples else None,
                pb_median=float(median(values["pb"])) if len(values["pb"]) >= minimum_samples else None,
                sample_size=min(len(values["pe"]), len(values["pb"])),
                source_ids=["industry-valuation-001"],
            )
            for trade_date, values in sorted(by_date.items())
            if len(values["pe"]) >= minimum_samples or len(values["pb"]) >= minimum_samples
        ]
        history_points = int(config["valuation_history_points"])
        if len(observations) > history_points:
            observations = _evenly_spaced_tail(observations, history_points)
        snapshot_ids = [item.snapshot_id for item in self._raw_snapshots[snapshot_start:]]
        return observations, snapshot_ids

    def _listed_stock_universe(self) -> list[dict[str, Any]]:
        if self._listed_universe_cache is None:
            self._listed_universe_cache = self._query(
                "stock_basic",
                list_status="L",
                fields=self.config["fundamental_peers"]["universe_fields"],
            )
        return list(self._listed_universe_cache)

    def get_money_flow(self, symbol: str, analysis_date: str) -> MoneyFlowSnapshot:
        signals = self.get_market_signals(symbol, analysis_date)
        normalized = normalize_symbol(symbol)
        tier_row = _latest_record(self._query("moneyflow", ts_code=normalized, trade_date=_compact_date(analysis_date)))
        margin = signals.margin_financing
        northbound = signals.northbound_holding
        margin_change: float | None = None
        if margin and margin.margin_balance and margin.margin_buy_amount is not None and margin.margin_repay_amount is not None:
            margin_change = (margin.margin_buy_amount - margin.margin_repay_amount) / margin.margin_balance * 100
        northbound_signal = "北向数据不可用"
        if northbound and northbound.holding_change is not None:
            northbound_signal = "北向持股增加" if northbound.holding_change > 0 else "北向持股减少" if northbound.holding_change < 0 else "北向持股持平"
        super_large = _tier_net(tier_row, "buy_elg_amount", "sell_elg_amount")
        large = _tier_net(tier_row, "buy_lg_amount", "sell_lg_amount")
        medium = _tier_net(tier_row, "buy_md_amount", "sell_md_amount")
        small = _tier_net(tier_row, "buy_sm_amount", "sell_sm_amount")
        main = _optional_number(tier_row, "net_mf_amount")
        if main is not None:
            main *= 10_000
        if margin or northbound or tier_row:
            source_type = "tushare_moneyflow_margin_hk_hold" if tier_row else "tushare_margin_hk_hold"
            self._record_evidence(
                "flow-001",
                f"{normalized} Tushare 分档资金/两融/北向",
                source_type,
                analysis_date,
                self._snapshot_ids(("moneyflow", "margin_detail", "hk_hold"), normalized, analysis_date),
            )
        return MoneyFlowSnapshot(
            main, super_large, margin_change, northbound_signal, 0.0, "大宗交易数据未获取",
            large_net_inflow=large, medium_net_inflow=medium, small_net_inflow=small, as_of=analysis_date,
        )

    def get_capital_flow_history(self, symbol: str, analysis_date: str) -> list[CapitalFlowObservation]:
        normalized = normalize_symbol(symbol)
        cache_key = (normalized, analysis_date)
        if cache_key in self._capital_flow_histories:
            return list(self._capital_flow_histories[cache_key])

        config = self.config["capital_flow_history"]
        end_date = _compact_date(analysis_date)
        start_date = (
            date.fromisoformat(analysis_date) - timedelta(days=int(config["calendar_lookback_days"]))
        ).strftime("%Y%m%d")
        money_rows = self._query(
            "moneyflow",
            ts_code=normalized,
            start_date=start_date,
            end_date=end_date,
        )
        margin_rows = self._query(
            "margin_detail",
            ts_code=normalized,
            start_date=start_date,
            end_date=end_date,
        )
        northbound_rows = self._query(
            "hk_hold",
            ts_code=normalized,
            start_date=start_date,
            end_date=end_date,
        )
        by_date: dict[str, dict[str, Any]] = {}
        for row in money_rows:
            trade_date = _iso_date(_text(row, "trade_date"))
            value = _optional_number(row, "net_mf_amount")
            if trade_date and value is not None:
                by_date.setdefault(trade_date, {})["main_net_inflow"] = value * 10_000
        for row in margin_rows:
            trade_date = _iso_date(_text(row, "trade_date"))
            value = _optional_number(row, "rzye")
            if trade_date and value is not None:
                by_date.setdefault(trade_date, {})["margin_balance"] = value
        northbound_changes = _holding_quantity_changes(northbound_rows)
        for trade_date, value in northbound_changes.items():
            by_date.setdefault(trade_date, {})["northbound_holding_change"] = value

        observations: list[CapitalFlowObservation] = []
        for trade_date, values in sorted(by_date.items()):
            source_ids: list[str] = []
            if "main_net_inflow" in values:
                source_ids.append("flow-history-001")
            if "margin_balance" in values:
                source_ids.append("margin-history-001")
            if "northbound_holding_change" in values:
                source_ids.append("northbound-history-001")
            observations.append(CapitalFlowObservation(
                trade_date=trade_date,
                main_net_inflow=values.get("main_net_inflow"),
                northbound_holding_change=values.get("northbound_holding_change"),
                margin_balance=values.get("margin_balance"),
                source_ids=source_ids,
            ))
        observations = observations[-int(config["history_points"]):]
        snapshot_ids = self._snapshot_ids(
            ("moneyflow", "margin_detail", "hk_hold"),
            normalized,
            analysis_date,
        )
        observations, quality = validate_dataset_records(
            provider="tushare",
            dataset="capital_flow_history",
            records=observations,
            analysis_date=analysis_date,
            snapshot_ids=snapshot_ids,
        )
        self._quality_reports[(normalized, analysis_date, "capital_flow_history")] = quality
        if observations:
            latest_date = observations[-1].trade_date
            source_specs = (
                ("flow-history-001", "主力资金历史", "tushare_moneyflow", "main_net_inflow", "moneyflow"),
                ("margin-history-001", "融资余额历史", "tushare_margin_detail", "margin_balance", "margin_detail"),
                ("northbound-history-001", "北向持股披露变化历史", "tushare_hk_hold", "northbound_holding_change", "hk_hold"),
            )
            for source_id, title, source_type, field_name, interface in source_specs:
                if any(getattr(item, field_name) is not None for item in observations):
                    self._record_evidence(
                        source_id,
                        f"{normalized} {title}",
                        source_type,
                        latest_date,
                        self._snapshot_ids((interface,), normalized, analysis_date),
                    )
        self._capital_flow_histories[cache_key] = list(observations)
        return list(observations)

    def get_dragon_tiger_history(self, symbol: str, analysis_date: str) -> list[DragonTigerSeatRecord]:
        normalized = normalize_symbol(symbol)
        cache_key = (normalized, analysis_date)
        if cache_key in self._dragon_tiger_histories:
            return list(self._dragon_tiger_histories[cache_key])
        config = self.config["dragon_tiger_history"]
        start_date = date.fromisoformat(analysis_date) - timedelta(days=int(config["calendar_lookback_days"]))
        snapshot_start = len(self._raw_snapshots)
        rows = self._query("top_inst", ts_code=normalized)
        snapshot_ids = [item.snapshot_id for item in self._raw_snapshots[snapshot_start:]]
        records = [
            _dragon_tiger_seat_record(row, self.config["top_inst_side_codes"], "dragon-tiger-history-001")
            for row in rows
            if _text(row, "ts_code") == normalized
            and _date_in_range(_text(row, "trade_date"), start_date, date.fromisoformat(analysis_date))
        ]
        records = sorted(records, key=lambda item: (item.trade_date, item.reason, item.seat_name, item.side))
        records = records[-int(config["maximum_records"]):]
        records, quality = validate_dataset_records(
            provider="tushare",
            dataset="dragon_tiger_history",
            records=records,
            analysis_date=analysis_date,
            snapshot_ids=snapshot_ids,
        )
        self._quality_reports[(normalized, analysis_date, "dragon_tiger_history")] = quality
        if records:
            self._record_evidence(
                "dragon-tiger-history-001",
                f"{normalized} 龙虎榜席位历史披露",
                "tushare_top_inst",
                records[-1].trade_date,
                quality.snapshot_ids,
            )
        self._dragon_tiger_histories[cache_key] = list(records)
        return list(records)

    def get_announcements(self, symbol: str, analysis_date: str) -> list[Announcement]:
        normalized = normalize_symbol(symbol)
        event_type_map = load_runtime_settings().get("domain_knowledge", "announcement_timeliness", "event_type_map")
        items = [
            Announcement(
                item.title,
                item.published_at,
                "company",
                item.impact,
                item.summary,
                item.source_id,
                event_type=event_type_map.get(item.event_type, "general"),
                report_period=item.report_period,
                forecast_net_profit_min_yuan=item.forecast_net_profit_min_yuan,
                forecast_net_profit_max_yuan=item.forecast_net_profit_max_yuan,
                actual_net_profit_yuan=item.actual_net_profit_yuan,
                first_announced_at=item.first_announced_at,
                url=item.url,
            )
            for item in self.get_market_signals(normalized, analysis_date).corporate_events
        ]
        items, quality = validate_dataset_records(
            provider="tushare",
            dataset="announcements",
            records=items,
            analysis_date=analysis_date,
            snapshot_ids=self._snapshot_ids(("forecast", "express", "income", "share_float", "stk_holdertrade"), normalized, analysis_date),
        )
        self._quality_reports[(normalized, analysis_date, "announcements")] = quality
        return items

    def get_market_context(self, analysis_date: str) -> MarketContext:
        cached = self._market_contexts.get(analysis_date)
        if cached is not None:
            return cached

        config = self.config["market_context"]
        end_date = _compact_date(analysis_date)
        start_date = (
            date.fromisoformat(analysis_date) - timedelta(days=int(config["calendar_lookback_days"]))
        ).strftime("%Y%m%d")
        index_rows = self._query(
            "index_daily",
            ts_code=config["index_code"],
            start_date=start_date,
            end_date=end_date,
        )
        index_by_date = {
            _text(row, "trade_date"): row
            for row in index_rows
            if _text(row, "trade_date") <= end_date
        }
        trade_dates = sorted(index_by_date)[-int(config["history_points"]):]
        history: list[MarketSentimentObservation] = []
        unavailable_reasons: list[str] = []
        previous_limit_up_symbols: set[str] = set()
        previous_first_board_symbols: set[str] = set()

        for trade_date in trade_dates:
            market_rows = self._query("daily", trade_date=trade_date)
            market_query_ok = self._last_query_succeeded("daily", trade_date=trade_date)
            limit_rows = self._query("limit_list", trade_date=trade_date)
            limit_query_ok = self._last_query_succeeded("limit_list", trade_date=trade_date)
            if not market_query_ok or not market_rows:
                unavailable_reasons.append(f"{_iso_date(trade_date)} 全市场日线不可用")
                previous_limit_up_symbols = set()
                previous_first_board_symbols = set()
                continue
            if not limit_query_ok:
                unavailable_reasons.append(f"{_iso_date(trade_date)} 涨跌停池不可用")
                previous_limit_up_symbols = set()
                previous_first_board_symbols = set()
                continue

            market_codes = [_text(row, "ts_code") for row in market_rows]
            pct_values = [_optional_number(row, "pct_chg") for row in market_rows]
            amount_values = [_optional_number(row, "amount") for row in market_rows]
            if (
                any(not code for code in market_codes)
                or len(set(market_codes)) != len(market_codes)
                or any(value is None for value in pct_values)
                or any(value is None for value in amount_values)
            ):
                unavailable_reasons.append(f"{_iso_date(trade_date)} 全市场日线存在缺失字段或重复代码")
                previous_limit_up_symbols = set()
                previous_first_board_symbols = set()
                continue
            limit_type_field = config["limit_type_field"]
            limit_codes = config["limit_type_codes"]
            times_field = config["limit_times_field"]
            open_times_field = config["limit_open_times_field"]
            first_time_field = config["limit_first_time_field"]
            allowed_limit_types = set(limit_codes.values())
            if any(
                not _text(row, "ts_code")
                or _text(row, limit_type_field) not in allowed_limit_types
                or (
                    _text(row, limit_type_field) == limit_codes["up"]
                    and (
                        _optional_number(row, times_field) is None
                        or _optional_number(row, open_times_field) is None
                        or not _text(row, first_time_field)
                    )
                )
                for row in limit_rows
            ):
                unavailable_reasons.append(f"{_iso_date(trade_date)} 涨跌停池字段不完整")
                previous_limit_up_symbols = set()
                previous_first_board_symbols = set()
                continue

            pct_changes = dict(zip(market_codes, (float(value) for value in pct_values if value is not None)))

            advance_threshold = float(config["advance_threshold_pct"])
            decline_threshold = float(config["decline_threshold_pct"])
            advancers = sum(value > advance_threshold for value in pct_changes.values())
            decliners = sum(value < decline_threshold for value in pct_changes.values())
            total_amount = sum(float(value) * 1000 for value in amount_values if value is not None)
            up_rows = [row for row in limit_rows if _text(row, limit_type_field) == limit_codes["up"]]
            down_rows = [row for row in limit_rows if _text(row, limit_type_field) == limit_codes["down"]]
            broken_rows = [row for row in limit_rows if _text(row, limit_type_field) == limit_codes["broken"]]
            current_limit_up_symbols = {_text(row, "ts_code") for row in up_rows if _text(row, "ts_code")}
            first_board_symbols = {
                _text(row, "ts_code")
                for row in up_rows
                if _text(row, "ts_code") and _number(row, times_field) == 1
            }
            max_boards = int(max((_number(row, times_field) for row in up_rows), default=0))
            failed_denominator = len(up_rows) + len(broken_rows)
            failed_rate = len(broken_rows) / failed_denominator * 100 if failed_denominator else 0.0
            sealed_rate = len(up_rows) / failed_denominator * 100 if failed_denominator else 0.0
            one_price_count = sum(
                _number(row, open_times_field) == 0
                and _text(row, first_time_field) in set(config["one_price_first_times"])
                for row in up_rows
            )
            board_ladder = _board_ladder(up_rows, times_field, config["board_ladder_buckets"])
            prior_limit_returns = [
                pct_changes[symbol]
                for symbol in previous_limit_up_symbols
                if symbol in pct_changes
            ]
            premium = _mean(prior_limit_returns)
            second_board_rate = (
                len(current_limit_up_symbols & previous_first_board_symbols)
                / len(previous_first_board_symbols)
                * 100
                if previous_first_board_symbols
                else 0.0
            )
            history.append(MarketSentimentObservation(
                trade_date=_iso_date(trade_date),
                limit_up_count=len(up_rows),
                limit_down_count=len(down_rows),
                failed_breakout_rate=failed_rate,
                yesterday_limit_up_premium=premium,
                max_consecutive_boards=max_boards,
                first_board_count=len(first_board_symbols),
                second_board_success_rate=second_board_rate,
                strong_stock_return=premium,
                total_amount=total_amount,
                advancers=advancers,
                decliners=decliners,
                sealed_limit_up_rate=sealed_rate,
                one_price_limit_up_count=one_price_count,
                broken_limit_up_count=len(broken_rows),
                board_ladder=board_ladder,
            ))
            previous_limit_up_symbols = current_limit_up_symbols
            previous_first_board_symbols = first_board_symbols

        snapshot_ids = self._market_snapshot_ids(analysis_date, ("index_daily", "daily", "limit_list"))
        valid_history, quality = validate_dataset_records(
            provider="tushare",
            dataset="market_sentiment",
            records=history,
            analysis_date=analysis_date,
            snapshot_ids=snapshot_ids,
        )
        invariant_issues = _market_sentiment_invariant_issues(valid_history)
        if invariant_issues:
            quality = replace(
                quality,
                status="failed",
                blocking=True,
                issues=[*quality.issues, *invariant_issues],
            )
        if trade_dates and len(valid_history) != len(trade_dates):
            quality = replace(
                quality,
                status="failed",
                completeness=round(len(valid_history) / len(trade_dates), 4),
                blocking=True,
                issues=[
                    *quality.issues,
                    DataQualityIssue(
                        code="non_contiguous_market_history",
                        severity="error",
                        message=(
                            f"Only {len(valid_history)} of {len(trade_dates)} selected trading days "
                            "have complete market breadth and limit-pool observations."
                        ),
                    ),
                ],
            )
        self._quality_reports[("__market__", analysis_date, "market_sentiment")] = quality
        latest_observation = valid_history[-1] if valid_history else None
        current = (
            latest_observation
            if latest_observation is not None and latest_observation.trade_date == analysis_date
            else None
        )
        current_index = index_by_date.get(current.trade_date.replace("-", ""), {}) if current else {}
        index_change_pct = _optional_number(current_index, "pct_chg")
        if current is not None and index_change_pct is None:
            unavailable_reasons.append(f"{current.trade_date} 指数涨跌幅字段为空")

        policy_themes = self._policy_themes(analysis_date, unavailable_reasons)
        provisional = MarketContext(
            index_name=config["index_name"],
            index_change_pct=index_change_pct,
            total_amount=current.total_amount if current else None,
            advancers=current.advancers if current else None,
            decliners=current.decliners if current else None,
            limit_up_count=current.limit_up_count if current else None,
            limit_down_count=current.limit_down_count if current else None,
            hot_money_cycle="数据不足",
            policy_themes=policy_themes,
            failed_breakout_rate=current.failed_breakout_rate if current else None,
            yesterday_limit_up_premium=current.yesterday_limit_up_premium if current else None,
            max_consecutive_boards=current.max_consecutive_boards if current else None,
            first_board_count=current.first_board_count if current else None,
            second_board_success_rate=current.second_board_success_rate if current else None,
            strong_stock_return=current.strong_stock_return if current else None,
            sealed_limit_up_rate=current.sealed_limit_up_rate if current else None,
            one_price_limit_up_count=current.one_price_limit_up_count if current else None,
            broken_limit_up_count=current.broken_limit_up_count if current else None,
            board_ladder=dict(current.board_ladder) if current else {},
            sentiment_history=valid_history,
            data_status=(
                "verified"
                if quality.status == "passed"
                and index_change_pct is not None
                and current is not None
                and current.trade_date == analysis_date
                else "insufficient"
            ),
            as_of=latest_observation.trade_date if latest_observation else None,
            unavailable_reasons=_unique(unavailable_reasons),
        )
        dynamics = analyze_sentiment_dynamics(provisional)
        resolved_cycle = dynamics.stage if provisional.data_status == "verified" else "数据不足"
        context = MarketContext(**{
            **provisional.__dict__,
            "hot_money_cycle": resolved_cycle,
            "data_status": (
                "verified"
                if provisional.data_status == "verified" and dynamics.insufficient_reason is None
                else "insufficient"
            ),
        })
        if context.data_status == "verified" and context.as_of:
            self._record_evidence(
                "market-001",
                f"{config['index_name']}、全市场宽度与涨跌停动态",
                "tushare_index_daily_daily_limit_list_d",
                context.as_of,
                snapshot_ids,
            )
            if config["limit_list_excludes_st"]:
                context = MarketContext(**{
                    **context.__dict__,
                    "unavailable_reasons": _unique([*context.unavailable_reasons, "涨跌停统计不含 ST 股票"]),
                })
        self._market_contexts[analysis_date] = context
        return context

    def get_ah_premium(self, symbol: str, analysis_date: str) -> AhPremiumSnapshot:
        normalized = normalize_symbol(symbol)
        ah_config = self.config["ah_premium"]
        available_since = str(ah_config["available_since"])
        if analysis_date < available_since:
            return AhPremiumSnapshot(
                data_status="unavailable",
                trade_date=analysis_date,
                a_symbol=normalized,
                unavailable_reasons=[
                    f"Tushare AH comparison coverage starts on {available_since}; "
                    f"analysis_date={analysis_date} is outside source coverage."
                ],
            )
        params = {"ts_code": normalized, "trade_date": _compact_date(analysis_date)}
        rows = self._query("ah_comparison", **params)
        query_ok = self._last_query_succeeded("ah_comparison", **params)
        if not query_ok:
            return AhPremiumSnapshot(
                data_status="unavailable",
                trade_date=analysis_date,
                a_symbol=normalized,
                unavailable_reasons=["Tushare AH comparison interface is unavailable or not entitled."],
            )
        if not rows:
            return AhPremiumSnapshot(
                data_status="not_applicable",
                trade_date=analysis_date,
                a_symbol=normalized,
                unavailable_reasons=["No A/H comparison record exists for this symbol and date."],
            )

        source_id = "ah-premium-001"
        observations = [
            AhPremiumSnapshot(
                data_status="verified",
                trade_date=_iso_date(_text(row, "trade_date")),
                a_symbol=_text(row, "ts_code"),
                h_symbol=_text(row, "hk_code") or None,
                a_close=_optional_number(row, "close"),
                h_close=_optional_number(row, "hk_close"),
                ah_comparison=_optional_number(row, "ah_comparison"),
                ah_premium_pct=_optional_number(row, "ah_premium"),
                source_id=source_id,
            )
            for row in rows
        ]
        snapshot_ids = self._snapshot_ids(("ah_comparison",), normalized, analysis_date)
        valid, quality = validate_dataset_records(
            provider="tushare",
            dataset="ah_premium",
            records=observations,
            analysis_date=analysis_date,
            snapshot_ids=snapshot_ids,
        )
        semantic_issues: list[DataQualityIssue] = []
        tolerance = float(ah_config["comparison_tolerance_pct"])
        for index, observation in enumerate(valid):
            if observation.a_symbol != normalized:
                semantic_issues.append(DataQualityIssue(
                    code="ah_symbol_mismatch",
                    severity="error",
                    message=(
                        f"AH record symbol={observation.a_symbol} does not match "
                        f"requested symbol={normalized}."
                    ),
                    field="a_symbol",
                    record_index=index,
                ))
            if observation.ah_comparison is not None and observation.ah_premium_pct is not None:
                implied_premium = (observation.ah_comparison - 1) * 100
                if abs(implied_premium - observation.ah_premium_pct) > tolerance:
                    semantic_issues.append(DataQualityIssue(
                        code="inconsistent_ah_comparison",
                        severity="error",
                        message=(
                            f"AH ratio implies premium={implied_premium:.4f}%, but source premium="
                            f"{observation.ah_premium_pct:.4f}% exceeds configured tolerance={tolerance}%."
                        ),
                        field="ah_premium_pct",
                        record_index=index,
                    ))
        if len(valid) != 1:
            semantic_issues.append(DataQualityIssue(
                code="ambiguous_ah_comparison",
                severity="error",
                message=f"Expected one aligned AH record, received {len(valid)} valid records.",
            ))
        if semantic_issues:
            quality = replace(
                quality,
                status="failed",
                valid_records=0,
                completeness=0.0,
                issues=[*quality.issues, *semantic_issues],
            )
            valid = []
        self._quality_reports[(normalized, analysis_date, "ah_premium")] = quality
        if len(valid) != 1:
            return AhPremiumSnapshot(
                data_status="unavailable",
                trade_date=analysis_date,
                a_symbol=normalized,
                unavailable_reasons=["AH comparison record failed uniqueness, date, or field quality checks."],
            )
        observation = valid[0]
        self._record_evidence(
            source_id,
            f"{normalized} Tushare AH comparison",
            "tushare_stk_ah_comparison",
            observation.trade_date,
            snapshot_ids,
        )
        return observation

    def _policy_themes(self, analysis_date: str, unavailable_reasons: list[str]) -> list[str]:
        config = self.config["market_context"]["policy_news"]
        if not config["enabled"]:
            return []
        params = {
            "start_date": f"{analysis_date} 00:00:00",
            "end_date": f"{analysis_date} 23:59:59",
            "fields": config["fields"],
        }
        rows = self._query("policy_news", **params)
        if not self._last_query_succeeded("policy_news", **params):
            unavailable_reasons.append("政策新闻接口不可用；政策主题维度不参与判断")
            return []
        scored: list[tuple[int, str]] = []
        for theme, keywords in config["theme_keywords"].items():
            mentions = sum(
                sum(str(row.get(field, "")).lower().count(str(keyword).lower()) for keyword in keywords)
                for row in rows
                for field in ("title", "content")
            )
            if mentions >= int(config["minimum_mentions"]):
                scored.append((mentions, theme))
        themes = [
            theme
            for _, theme in sorted(scored, key=lambda item: (-item[0], item[1]))[:int(config["maximum_themes"])]
        ]
        if themes:
            self._record_evidence(
                "policy-theme-001",
                "Tushare 政策新闻主题匹配",
                "tushare_major_news_deterministic_keyword_match",
                analysis_date,
                self._market_snapshot_ids(analysis_date, ("policy_news",)),
            )
        return themes

    def get_convertible_bond_snapshot(self, symbol: str, analysis_date: str) -> ConvertibleBondSnapshot:
        normalized = normalize_symbol(symbol)
        basic = _latest_record(self._query("cb_basic", ts_code=normalized))
        daily = _latest_record(self._query("cb_daily", ts_code=normalized, trade_date=_compact_date(analysis_date)))
        underlying_code = _text(basic, "stk_code")
        underlying = _latest_record(self._query("daily", ts_code=underlying_code, trade_date=_compact_date(analysis_date))) if underlying_code else {}
        source_ids: list[str] = []
        if basic:
            source_ids.append("cb-basic-001")
            self._record_evidence("cb-basic-001", f"{normalized} Tushare 可转债基础信息", "tushare_cb_basic", analysis_date)
        if daily:
            source_ids.append("cb-daily-001")
            self._record_evidence("cb-daily-001", f"{normalized} Tushare 可转债行情", "tushare_cb_daily", _iso_date(_text(daily, "trade_date")))
        if underlying:
            source_ids.append("cb-underlying-001")
            self._record_evidence("cb-underlying-001", f"{underlying_code} Tushare 正股行情", "tushare_daily", _iso_date(_text(underlying, "trade_date")))
        amount = _optional_number(daily, "amount")
        return ConvertibleBondSnapshot(
            symbol=normalized,
            name=_text(basic, "bond_short_name", default=normalized),
            as_of=_iso_date(_text(daily, "trade_date", default=analysis_date)),
            bond_price=_optional_number(daily, "close"),
            underlying_price=_optional_number(underlying, "close"),
            conversion_price=_optional_number(basic, "conv_price"),
            remaining_balance=_optional_number(basic, "remain_size"),
            amount=amount * 10_000 if amount is not None else None,
            maturity_date=_iso_date(_text(basic, "maturity_date")) or None,
            source_ids=source_ids,
        )

    def get_evidence_sources(self, symbol: str, analysis_date: str) -> list[EvidenceSource]:
        return list(self._evidence.values())

    def get_raw_snapshots(self, symbol: str, analysis_date: str) -> list[RawDataSnapshot]:
        normalized = normalize_symbol(symbol)
        referenced_snapshot_ids = {
            snapshot_id
            for source in self._evidence.values()
            for snapshot_id in source.snapshot_ids
        }
        market_interfaces = {
            self.config["interfaces"][key]
            for key in ("index_daily", "daily", "limit_list", "policy_news")
        }
        earliest = date.fromisoformat(analysis_date) - timedelta(
            days=int(self.config["market_context"]["calendar_lookback_days"])
        )
        return [
            item
            for item in self._raw_snapshots
            if item.snapshot_id in referenced_snapshot_ids
            or snapshot_matches(item, normalized, analysis_date)
            or (
                item.interface in market_interfaces
                and item.analysis_date is not None
                and earliest <= date.fromisoformat(item.analysis_date) <= date.fromisoformat(analysis_date)
                and (
                    item.symbol is None
                    or item.symbol == self.config["market_context"]["index_code"]
                )
            )
        ]

    def get_data_quality_reports(self, symbol: str, analysis_date: str) -> list[DataQualityReport]:
        normalized = normalize_symbol(symbol)
        semantic = [
            report
            for (report_symbol, report_date, _), report in self._quality_reports.items()
            if report_symbol in {normalized, "__market__"} and report_date == analysis_date
        ]
        raw = [validate_raw_snapshot(item) for item in self.get_raw_snapshots(normalized, analysis_date)]
        return [*semantic, *raw]

    def get_market_signals(self, symbol: str, analysis_date: str) -> AshareMarketSignals:
        normalized = normalize_symbol(symbol)
        cache_key = (normalized, analysis_date)
        if cache_key in self._signals:
            return self._signals[cache_key]
        trade_date = _compact_date(analysis_date)
        dragon = self._dragon_tiger(normalized, trade_date)
        margin = self._margin(normalized, trade_date)
        northbound = self._northbound(normalized, trade_date)
        events = self._corporate_events(normalized, analysis_date)
        status = "verified" if self.configured and any([dragon, margin, northbound, events]) else "unavailable"
        reasons = list(self._errors) if status == "unavailable" else []
        quality_reports = [
            report
            for (report_symbol, report_date, _), report in self._quality_reports.items()
            if report_symbol == normalized and report_date == analysis_date
        ]
        signals = AshareMarketSignals(
            status,
            dragon,
            margin,
            northbound,
            events,
            list(self._evidence.values()),
            reasons,
            quality_reports,
        )
        self._signals[cache_key] = signals
        return signals

    def _dragon_tiger(self, symbol: str, trade_date: str) -> list[DragonTigerRecord]:
        rows = [row for row in self._query("top_list", ts_code=symbol, trade_date=trade_date) if _text(row, "ts_code") == symbol]
        institution_rows = [row for row in self._query("top_inst", ts_code=symbol, trade_date=trade_date) if _text(row, "ts_code") == symbol]
        side_codes = self.config["top_inst_side_codes"]
        institution_by_reason: dict[str, list[dict[str, Any]]] = {}
        for row in institution_rows:
            institution_by_reason.setdefault(_text(row, "reason"), []).append(row)
        records: list[DragonTigerRecord] = []
        for row in rows:
            reason = _text(row, "reason", default="龙虎榜上榜")
            matched = institution_by_reason.get(reason, institution_rows if len(rows) == 1 else [])
            institution_keywords = load_runtime_settings().get("domain_knowledge", "dragon_tiger_depth", "institution_keywords")
            institution_net = sum(
                _number(item, "net_buy")
                for item in matched
                if any(keyword in _text(item, "exalter") for keyword in institution_keywords)
            ) or None
            seat_records = [
                _dragon_tiger_seat_record(item, side_codes, "dragon-tiger-001")
                for item in matched
                if _text(item, "exalter")
            ]
            records.append(DragonTigerRecord(
                _iso_date(_text(row, "trade_date", default=trade_date)),
                reason,
                _number(row, "net_amount"),
                institution_net,
                buy_seats=[_text(item, "exalter") for item in matched if _text(item, "side") == side_codes["buy"] and _text(item, "exalter")],
                sell_seats=[_text(item, "exalter") for item in matched if _text(item, "side") == side_codes["sell"] and _text(item, "exalter")],
                source_id="dragon-tiger-001",
                seat_records=seat_records,
            ))
        analysis_date = _iso_date(trade_date)
        records, quality = validate_dataset_records(
            provider="tushare",
            dataset="dragon_tiger",
            records=records,
            analysis_date=analysis_date,
            snapshot_ids=self._snapshot_ids(("top_list", "top_inst"), symbol, analysis_date),
        )
        self._quality_reports[(symbol, analysis_date, "dragon_tiger")] = quality
        if records:
            self._record_evidence(
                "dragon-tiger-001",
                f"{symbol} 龙虎榜/机构席位",
                "tushare_top_list_top_inst",
                records[0].trade_date,
                quality.snapshot_ids,
            )
        return records

    def _margin(self, symbol: str, trade_date: str) -> MarginFinancingRecord | None:
        row = _latest_record(self._query("margin_detail", ts_code=symbol, trade_date=trade_date))
        analysis_date = _iso_date(trade_date)
        if not row:
            _, quality = validate_dataset_records(
                provider="tushare",
                dataset="margin_financing",
                records=[],
                analysis_date=analysis_date,
                snapshot_ids=self._snapshot_ids(("margin_detail",), symbol, analysis_date),
            )
            self._quality_reports[(symbol, analysis_date, "margin_financing")] = quality
            return None
        result = MarginFinancingRecord(_iso_date(_text(row, "trade_date", default=trade_date)), _optional_number(row, "rzye"), _optional_number(row, "rqye"), _optional_number(row, "rzmre"), _optional_number(row, "rzche"), "margin-001")
        valid, quality = validate_dataset_records(
            provider="tushare",
            dataset="margin_financing",
            records=[result],
            analysis_date=analysis_date,
            snapshot_ids=self._snapshot_ids(("margin_detail",), symbol, analysis_date),
        )
        self._quality_reports[(symbol, analysis_date, "margin_financing")] = quality
        if not valid:
            return None
        result = valid[0]
        self._record_evidence(
            "margin-001",
            f"{symbol} 融资融券明细",
            "tushare_margin_detail",
            result.trade_date,
            quality.snapshot_ids,
        )
        return result

    def _northbound(self, symbol: str, trade_date: str) -> NorthboundHoldingRecord | None:
        analysis_date = _iso_date(trade_date)
        lookback_days = int(self.config["capital_flow_history"]["calendar_lookback_days"])
        start_date = (date.fromisoformat(analysis_date) - timedelta(days=lookback_days)).strftime("%Y%m%d")
        rows = self._query(
            "hk_hold",
            ts_code=symbol,
            start_date=start_date,
            end_date=trade_date,
        )
        ordered_rows = sorted(rows, key=lambda item: _text(item, "trade_date"))
        row = ordered_rows[-1] if ordered_rows else None
        changes = _holding_quantity_changes(ordered_rows)
        if not row:
            _, quality = validate_dataset_records(
                provider="tushare",
                dataset="northbound_holding",
                records=[],
                analysis_date=analysis_date,
                snapshot_ids=self._snapshot_ids(("hk_hold",), symbol, analysis_date),
            )
            self._quality_reports[(symbol, analysis_date, "northbound_holding")] = quality
            return None
        quantity = _optional_number(row, "vol")
        value = _optional_number(row, "amount")
        observed_date = _iso_date(_text(row, "trade_date", default=trade_date))
        result = NorthboundHoldingRecord(
            observed_date,
            quantity,
            value,
            changes.get(observed_date),
            "northbound-001",
        )
        valid, quality = validate_dataset_records(
            provider="tushare",
            dataset="northbound_holding",
            records=[result],
            analysis_date=analysis_date,
            snapshot_ids=self._snapshot_ids(("hk_hold",), symbol, analysis_date),
        )
        self._quality_reports[(symbol, analysis_date, "northbound_holding")] = quality
        if not valid:
            return None
        result = valid[0]
        self._record_evidence(
            "northbound-001",
            f"{symbol} 沪深股通相邻披露期持股变化",
            "tushare_hk_hold",
            result.trade_date,
            quality.snapshot_ids,
        )
        return result

    def _corporate_events(self, symbol: str, analysis_date: str) -> list[CorporateEvent]:
        events: list[CorporateEvent] = []
        event_specs = (("forecast", "业绩预告", "negative"), ("express", "业绩快报", "neutral"), ("income", "实际业绩", "neutral"), ("share_float", "限售解禁", "negative"), ("stk_holdertrade", "股东增减持", "negative"))
        for interface, event_type, default_impact in event_specs:
            snapshot_start = len(self._raw_snapshots)
            rows = self._query(interface, ts_code=symbol)
            snapshot_ids = [item.snapshot_id for item in self._raw_snapshots[snapshot_start:]]
            for row in rows:
                published_at = _iso_date(_text(row, "ann_date", "f_ann_date", "trade_date", default=analysis_date))
                if published_at > analysis_date:
                    continue
                impact = _event_impact(_text(row, "type", "in_de", "trade_type"), default_impact)
                title = f"{event_type}：{_text(row, 'holder_name', 'end_date', default=symbol)}"
                summary = _event_summary(row, event_type)
                source_id = f"event-{interface}-" + hashlib.sha256(
                    f"{symbol}|{published_at}|{_text(row, 'end_date')}|{title}".encode("utf-8")
                ).hexdigest()[:12]
                forecast_min = _optional_number(row, "net_profit_min")
                forecast_max = _optional_number(row, "net_profit_max")
                events.append(CorporateEvent(
                    event_type,
                    title,
                    published_at,
                    impact,
                    summary,
                    source_id,
                    report_period=_iso_date(_text(row, "end_date")) or None,
                    forecast_net_profit_min_yuan=forecast_min * 10_000 if interface == "forecast" and forecast_min is not None else None,
                    forecast_net_profit_max_yuan=forecast_max * 10_000 if interface == "forecast" and forecast_max is not None else None,
                    actual_net_profit_yuan=_optional_number(row, "n_income") if interface in {"express", "income"} else None,
                    first_announced_at=_iso_date(_text(row, "first_ann_date")) or None,
                ))
                self._record_evidence(
                    source_id,
                    f"{symbol} {event_type}",
                    f"tushare_{interface}",
                    published_at,
                    snapshot_ids,
                )
        return events

    def _query(self, interface_key: str, **kwargs: object) -> list[dict[str, Any]]:
        method_name = self.config["interfaces"][interface_key]
        if self._client is None:
            message = "Tushare client is unavailable; configure the package and token."
            self._errors.append(message)
            self._capture(method_name, kwargs, [], "error", message)
            return []
        try:
            response = getattr(self._client, method_name)(**kwargs)
            records = _records(response)
            self._capture(method_name, kwargs, records, "success")
            return records
        except Exception as exc:  # provider entitlement/rate-limit failures must remain visible as unavailable data
            message = f"Tushare {method_name} unavailable: {exc}"
            self._errors.append(message)
            self._capture(method_name, kwargs, [], "error", message)
            return []

    def _capture(
        self,
        interface: str,
        params: dict[str, object],
        records: list[dict[str, Any]],
        status: str,
        error: str | None = None,
    ) -> None:
        self._query_outcomes.append((interface, dict(params), status))
        if not load_runtime_settings().get("data_quality", "raw_snapshots", "enabled"):
            return
        snapshot = build_raw_snapshot(
            provider="tushare",
            interface=interface,
            request_params=params,
            records=records,
            status=status,
            error=error,
        )
        self._raw_store.save(snapshot)
        self._raw_snapshots.append(snapshot)

    def _last_query_succeeded(self, interface_key: str, **expected_params: object) -> bool:
        method_name = self.config["interfaces"][interface_key]
        for interface, params, status in reversed(self._query_outcomes):
            if interface != method_name:
                continue
            if all(params.get(key) == value for key, value in expected_params.items()):
                return status == "success"
        return False

    def _snapshot_ids(
        self,
        interfaces: tuple[str, ...],
        symbol: str,
        analysis_date: str,
    ) -> list[str]:
        method_names = {self.config["interfaces"][item] for item in interfaces}
        return [
            item.snapshot_id
            for item in self.get_raw_snapshots(symbol, analysis_date)
            if item.interface in method_names
        ]

    def _market_snapshot_ids(
        self,
        analysis_date: str,
        interfaces: tuple[str, ...],
    ) -> list[str]:
        method_names = {self.config["interfaces"][item] for item in interfaces}
        return [
            item.snapshot_id
            for item in self.get_raw_snapshots("__market__", analysis_date)
            if item.interface in method_names
        ]

    def _record_evidence(
        self,
        source_id: str,
        title: str,
        source_type: str,
        as_of: str,
        snapshot_ids: list[str] | None = None,
    ) -> None:
        self._evidence[source_id] = EvidenceSource(
            source_id,
            title,
            source_type,
            as_of,
            snapshot_ids=list(snapshot_ids or []),
        )

    def _build_client(self) -> TushareClient | None:
        if not self.config["enabled"]:
            return None
        token = os.getenv(self.config["token_env"])
        if not token:
            return None
        try:
            import tushare as ts
        except ImportError:
            return None
        return ts.pro_api(token)


def _records(table: object) -> list[dict[str, Any]]:
    if table is None:
        return []
    if isinstance(table, list):
        return [dict(item) for item in table if isinstance(item, dict)]
    to_dict = getattr(table, "to_dict", None)
    if callable(to_dict):
        records = to_dict("records")
        return [dict(item) for item in records]
    raise TypeError("Tushare response must be a DataFrame-like object or record list")


def _latest_record(records: list[dict[str, Any]]) -> dict[str, Any]:
    return max(records, key=lambda item: _text(item, "trade_date", "ann_date", "end_date", default=""), default={})


def _latest_available_record(records: list[dict[str, Any]], analysis_date: str) -> dict[str, Any]:
    available = [item for item in records if _record_available_on(item, analysis_date)]
    return _latest_record(available)


def _record_available_on(record: dict[str, Any], analysis_date: str) -> bool:
    source_date = _text(record, "trade_date", "ann_date", "end_date")
    return bool(source_date) and _compact_date(source_date) <= _compact_date(analysis_date)


def _text(row: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() not in {"", "nan", "None"}:
            return str(value).strip()
    return default


def _number(row: dict[str, Any], key: str) -> float:
    return _optional_number(row, key) or 0.0


def _optional_number(row: dict[str, Any], key: str) -> float | None:
    value = row.get(key)
    try:
        return None if value is None or str(value).lower() == "nan" else float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(row: dict[str, Any], key: str) -> int | None:
    value = _optional_number(row, key)
    return int(value) if value is not None else None


def _industry_names_match(left: str, right: str, aliases: dict[str, list[str]]) -> bool:
    normalized_left = "".join(str(left).split()).casefold()
    normalized_right = "".join(str(right).split()).casefold()
    if not normalized_left or not normalized_right:
        return False
    if normalized_left == normalized_right:
        return True
    for canonical, variants in aliases.items():
        normalized_group = {
            "".join(str(item).split()).casefold()
            for item in [canonical, *variants]
        }
        if normalized_left in normalized_group and normalized_right in normalized_group:
            return True
    return False


def _evenly_spaced_tail(
    observations: list[IndustryValuationObservation],
    maximum_points: int,
) -> list[IndustryValuationObservation]:
    if len(observations) <= maximum_points:
        return observations
    if maximum_points == 1:
        return [observations[-1]]
    last_index = len(observations) - 1
    indexes = sorted({round(index * last_index / (maximum_points - 1)) for index in range(maximum_points)})
    return [observations[index] for index in indexes]


def _tier_net(row: dict[str, Any], buy_key: str, sell_key: str) -> float | None:
    buy = _optional_number(row, buy_key)
    sell = _optional_number(row, sell_key)
    if buy is None or sell is None:
        return None
    return (buy - sell) * 10_000


def _holding_quantity_changes(records: list[dict[str, Any]]) -> dict[str, float]:
    """Derive disclosed holding changes from adjacent hk_hold ``vol`` values.

    Tushare's hk_hold contract exposes total holding quantity, not a hold_change
    field.  Keeping this derivation here makes the semantics deterministic and
    prevents a missing vendor field from being silently interpreted as zero.
    """
    quantities: dict[str, float] = {}
    for row in records:
        trade_date = _iso_date(_text(row, "trade_date"))
        quantity = _optional_number(row, "vol")
        if trade_date and quantity is not None:
            quantities[trade_date] = quantity
    ordered = sorted(quantities.items())
    return {
        trade_date: quantity - previous_quantity
        for (previous_date, previous_quantity), (trade_date, quantity) in zip(ordered, ordered[1:])
        if trade_date > previous_date
    }


def _board_ladder(
    up_rows: list[dict[str, Any]],
    times_field: str,
    buckets: list[dict[str, Any]],
) -> dict[str, int]:
    ladder: dict[str, int] = {}
    board_counts = [_optional_int(row, times_field) for row in up_rows]
    for bucket in buckets:
        label = str(bucket["label"])
        minimum = int(bucket["minimum"])
        maximum = bucket.get("maximum")
        ladder[label] = sum(
            value is not None
            and value >= minimum
            and (maximum is None or value <= int(maximum))
            for value in board_counts
        )
    return ladder


def _market_sentiment_invariant_issues(
    observations: list[MarketSentimentObservation],
) -> list[DataQualityIssue]:
    issues: list[DataQualityIssue] = []
    for index, item in enumerate(observations):
        touched = item.limit_up_count + int(item.broken_limit_up_count or 0)
        sealed_rate = float(item.sealed_limit_up_rate or 0)
        failed_rate = float(item.failed_breakout_rate)
        rates_are_consistent = (
            abs(failed_rate) < 1e-9
            and abs(sealed_rate) < 1e-9
            if touched == 0
            else abs(failed_rate + sealed_rate - 100) < 1e-6
        )
        ladder_is_consistent = sum(item.board_ladder.values()) == item.limit_up_count
        values_are_bounded = (
            0 <= sealed_rate <= 100
            and 0 <= failed_rate <= 100
            and int(item.broken_limit_up_count or 0) >= 0
            and int(item.one_price_limit_up_count or 0) >= 0
            and int(item.one_price_limit_up_count or 0) <= item.limit_up_count
            and all(value >= 0 for value in item.board_ladder.values())
        )
        if not rates_are_consistent:
            issues.append(DataQualityIssue(
                code="inconsistent_limit_rates",
                severity="error",
                message="Sealed and failed-breakout rates do not share a consistent touched-limit denominator.",
                record_index=index,
            ))
        if not ladder_is_consistent:
            issues.append(DataQualityIssue(
                code="inconsistent_board_ladder",
                severity="error",
                message="Configured board-ladder buckets do not account for every sealed limit-up.",
                record_index=index,
            ))
        if not values_are_bounded:
            issues.append(DataQualityIssue(
                code="invalid_a_share_characteristic_bounds",
                severity="error",
                message=(
                    "A-share limit rates/counts must be non-negative, rates must be within 0..100, "
                    "and one-price boards cannot exceed sealed limit-ups."
                ),
                record_index=index,
            ))
    return issues


def _dragon_tiger_seat_record(
    row: dict[str, Any],
    side_codes: dict[str, str],
    source_id: str,
) -> DragonTigerSeatRecord:
    raw_side = _text(row, "side")
    side = "buy" if raw_side == side_codes["buy"] else "sell" if raw_side == side_codes["sell"] else "unknown"
    return DragonTigerSeatRecord(
        trade_date=_iso_date(_text(row, "trade_date")),
        reason=_text(row, "reason", default="未披露上榜原因"),
        seat_name=_text(row, "exalter", default="未披露席位"),
        side=side,
        buy_amount=_optional_number(row, "buy"),
        sell_amount=_optional_number(row, "sell"),
        net_buy_amount=_optional_number(row, "net_buy"),
        buy_rate=_optional_number(row, "buy_rate"),
        sell_rate=_optional_number(row, "sell_rate"),
        source_id=source_id,
    )


def _date_in_range(value: str, start: date, end: date) -> bool:
    try:
        observed = date.fromisoformat(_iso_date(value))
    except ValueError:
        return False
    return start <= observed <= end


def _compact_date(value: str) -> str:
    return value.replace("-", "")


def _iso_date(value: str) -> str:
    return value if "-" in value else f"{value[:4]}-{value[4:6]}-{value[6:8]}" if len(value) == 8 else value


def _event_summary(row: dict[str, Any], event_type: str) -> str:
    if event_type == "限售解禁":
        return f"解禁数量：{_text(row, 'float_share', default='未披露')}"
    if event_type == "股东增减持":
        return f"变动类型：{_text(row, 'in_de', 'trade_type', default='未披露')}；变动数量：{_text(row, 'change_vol', default='未披露')}"
    return f"报告期：{_text(row, 'end_date', default='未披露')}；预告类型：{_text(row, 'type', default='未披露')}"


def _event_impact(raw_type: str, default: str) -> str:
    config = load_runtime_settings().get("providers", "event_sentiment")
    if raw_type in config["positive_forecast_types"] or raw_type.upper() in config["positive_holder_trade_types"]:
        return "positive"
    if raw_type in config["negative_forecast_types"] or raw_type.upper() in config["negative_holder_trade_types"]:
        return "negative"
    return default


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
