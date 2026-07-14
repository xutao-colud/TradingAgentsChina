from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Protocol

from app.config.runtime import load_runtime_settings
from app.network.retry import retry_call
from app.data.providers.base import ProviderAdapter, ProviderCapabilities
from app.data.quality import validate_dataset_records, validate_raw_snapshot
from app.data.raw_snapshots import (
    InMemoryRawSnapshotStore,
    LocalRawSnapshotStore,
    RawDataSnapshot,
    RawSnapshotStore,
    build_raw_snapshot,
    snapshot_is_intact,
    snapshot_matches,
)
from app.rules.trading_rules import normalize_symbol
from app.schemas.report import (
    Announcement, AshareMarketSignals, CorporateEvent, DailyPrice, DataQualityIssue, DataQualityReport, EvidenceSource, IntradayBar,
    IntradaySnapshot, MarketContext, NorthboundHoldingRecord, OrderBookLevel,
)


class AkshareClient(Protocol):
    def __getattr__(self, name: str) -> Any: ...


class AkshareSupplementProvider(ProviderAdapter):
    """Public-data supplement for daily bars, northbound holdings and holder trades.

    This adapter intentionally exposes only fields with a known source and
    timestamp. It does not invent results when a public endpoint changes.
    """

    def __init__(
        self,
        client: AkshareClient | None = None,
        today: Callable[[], date] | None = None,
        raw_store: RawSnapshotStore | None = None,
        enable_slow_bulk_queries: bool | None = None,
    ) -> None:
        self.config = load_runtime_settings().get("providers", "akshare")
        self._client = client or self._build_client()
        self._today = today or date.today
        self._raw_store = raw_store or InMemoryRawSnapshotStore()
        bulk_config = self.config["bulk_snapshot_cache"]
        self._enable_slow_bulk_queries = (
            bool(bulk_config["slow_bulk_queries_enabled"])
            if enable_slow_bulk_queries is None
            else enable_slow_bulk_queries
        )
        self._raw_snapshots: list[RawDataSnapshot] = []
        self._call_outcomes: list[tuple[str, dict[str, object], str]] = []
        self._quality_reports: dict[tuple[str, str, str], DataQualityReport] = {}
        self._announcement_sources: dict[tuple[str, str], list[EvidenceSource]] = {}
        self._market_sources: dict[str, list[EvidenceSource]] = {}
        self._errors: list[str] = []

    @property
    def configured(self) -> bool:
        return self._client is not None

    def get_provider_capabilities(self) -> list[ProviderCapabilities]:
        return [ProviderCapabilities(
            provider="akshare",
            datasets=frozenset(self.config["capabilities"]),
            persists_raw_snapshots=isinstance(self._raw_store, LocalRawSnapshotStore),
        )]

    def get_daily_prices(self, symbol: str, analysis_date: str, lookback_days: int) -> list[DailyPrice]:
        start = (date.fromisoformat(analysis_date) - timedelta(days=max(lookback_days * 3, 90))).strftime("%Y%m%d")
        rows = self._call(
            "daily",
            symbol=normalize_symbol(symbol).split(".")[0],
            period="daily",
            start_date=start,
            end_date=analysis_date.replace("-", ""),
            adjust="",
            timeout=load_runtime_settings().get("runtime", "network_timeout_seconds"),
        )
        prices = [
            DailyPrice(
                trade_date=_date_text(row, "日期"), open=_number(row, "开盘"), high=_number(row, "最高"), low=_number(row, "最低"),
                close=_number(row, "收盘"), volume=_number(row, "成交量"), amount=_number(row, "成交额"), turnover_rate=_number(row, "换手率"),
            )
            for row in rows
        ]
        normalized = normalize_symbol(symbol)
        prices, quality = validate_dataset_records(
            provider="akshare",
            dataset="daily_prices",
            records=prices,
            analysis_date=analysis_date,
            snapshot_ids=self._snapshot_ids(("daily",), normalized, analysis_date),
        )
        self._quality_reports[(normalized, analysis_date, "daily_prices")] = quality
        return prices[-lookback_days:]

    def get_market_signals(self, symbol: str, analysis_date: str) -> AshareMarketSignals:
        code = normalize_symbol(symbol).split(".")[0]
        northbound = self._northbound(code, analysis_date)
        events = self._holder_trades(code, analysis_date)
        holder_quality = self._quality_reports.get((normalize_symbol(symbol), analysis_date, "holder_trades"))
        sources: list[EvidenceSource] = []
        if northbound:
            sources.append(EvidenceSource(
                "northbound-akshare-001",
                f"{code} 北向持股排行",
                "akshare_stock_hsgt_hold_stock_em",
                northbound.trade_date,
                snapshot_ids=self._snapshot_ids(("northbound",), normalize_symbol(symbol), analysis_date),
            ))
        if events:
            sources.append(EvidenceSource(
                "holder-trade-akshare-001",
                f"{code} 股东增减持",
                "akshare_stock_ggcg_em",
                max(item.published_at for item in events),
                snapshot_ids=holder_quality.snapshot_ids if holder_quality else [],
            ))
        if holder_quality and holder_quality.status == "passed":
            sources.append(EvidenceSource(
                "holder-trade-coverage-akshare-001",
                f"{code} AkShare 股东增减持覆盖",
                "akshare_stock_ggcg_em",
                analysis_date,
                snapshot_ids=holder_quality.snapshot_ids,
            ))
        status = "verified" if sources else "unavailable"
        quality_reports = [
            report
            for (report_symbol, report_date, _), report in self._quality_reports.items()
            if report_symbol == normalize_symbol(symbol) and report_date == analysis_date
        ]
        return AshareMarketSignals(
            status,
            northbound_holding=northbound,
            corporate_events=events,
            evidence_sources=sources,
            unavailable_reasons=[] if sources else list(self._errors),
            quality_reports=quality_reports,
        )

    def get_market_context(self, analysis_date: str) -> MarketContext:
        """Return a real current-session breadth snapshot without relabelling history.

        AkShare's all-A-share quote table is a current snapshot. Historical market
        breadth remains a Tushare responsibility because using today's breadth for
        an earlier analysis date would create look-ahead contamination.
        """
        if analysis_date != self._today().isoformat():
            return MarketContext(
                index_name=self.config["market_context"]["index_name"],
                index_change_pct=None,
                total_amount=None,
                advancers=None,
                decliners=None,
                limit_up_count=None,
                limit_down_count=None,
                hot_money_cycle="数据不足",
                policy_themes=[],
                data_status="unavailable",
                as_of=None,
                unavailable_reasons=["AkShare 全市场行情是当日截面，不能用于历史日期分析。"],
            )

        config = self.config["market_context"]
        fields = config["fields"]
        compact_date = analysis_date.replace("-", "")
        spot_rows = self._call("market_spot")
        index_rows = self._call("index_spot", symbol=config["index_series"])
        up_rows = self._call("limit_up", date=compact_date)
        down_rows = self._call("limit_down", date=compact_date)
        broken_rows = self._call("limit_broken", date=compact_date)
        calls_ok = all(
            self._last_call_succeeded(key, **params)
            for key, params in (
                ("market_spot", {}),
                ("index_spot", {"symbol": config["index_series"]}),
                ("limit_up", {"date": compact_date}),
                ("limit_down", {"date": compact_date}),
                ("limit_broken", {"date": compact_date}),
            )
        )
        index_row = next(
            (row for row in index_rows if _text(row, fields["code"]) == str(config["index_code"])),
            None,
        )
        pct_changes = [_optional_number(row, fields["pct_change"]) for row in spot_rows]
        amounts = [_optional_number(row, fields["amount"]) for row in spot_rows]
        complete_spot = bool(spot_rows) and all(value is not None for value in pct_changes + amounts)
        board_values = [_optional_number(row, fields["board_count"]) for row in up_rows]
        complete_limit = self._last_call_succeeded("limit_up", date=compact_date) and all(
            value is not None for value in board_values
        )
        index_change = _optional_number(index_row or {}, fields["pct_change"])

        market_rules = load_runtime_settings().get("providers", "tushare", "market_context")
        advancers = (
            sum(float(value) > float(market_rules["advance_threshold_pct"]) for value in pct_changes if value is not None)
            if complete_spot
            else None
        )
        decliners = (
            sum(float(value) < float(market_rules["decline_threshold_pct"]) for value in pct_changes if value is not None)
            if complete_spot
            else None
        )
        total_amount = sum(float(value) for value in amounts if value is not None) if complete_spot else None
        failed_denominator = len(up_rows) + len(broken_rows)
        failed_rate = len(broken_rows) / failed_denominator * 100 if failed_denominator else None
        sealed_rate = len(up_rows) / failed_denominator * 100 if failed_denominator else None
        first_times = set(market_rules["one_price_first_times"])
        one_price_count = (
            sum(
                _number(row, fields["open_count"]) <= float(market_rules["one_price_max_open_count"])
                and _text(row, fields["first_limit_time"]) in first_times
                for row in up_rows
            )
            if complete_limit
            else None
        )
        board_ladder = (
            _configured_board_ladder(up_rows, fields["board_count"], market_rules["board_ladder_buckets"])
            if complete_limit
            else {}
        )
        normalized_record = {
            "trade_date": analysis_date,
            "index_change_pct": index_change,
            "total_amount": total_amount,
            "advancers": advancers,
            "decliners": decliners,
            "limit_up_count": len(up_rows) if calls_ok else None,
            "limit_down_count": len(down_rows) if calls_ok else None,
            "failed_breakout_rate": failed_rate,
            "sealed_limit_up_rate": sealed_rate,
            "one_price_limit_up_count": one_price_count,
            "broken_limit_up_count": len(broken_rows) if calls_ok else None,
            "board_ladder": board_ladder,
        }
        snapshot_ids = self._market_snapshot_ids(analysis_date)
        valid, quality = validate_dataset_records(
            provider="akshare",
            dataset="market_breadth_current",
            records=[normalized_record] if calls_ok else [],
            analysis_date=analysis_date,
            snapshot_ids=snapshot_ids,
        )
        self._quality_reports[("__market__", analysis_date, "market_breadth_current")] = quality
        verified = bool(valid) and quality.status == "passed"
        reasons: list[str] = ["AkShare 当日截面不提供连续市场情绪历史；情绪速度/加速度保持数据不足。"]
        if not verified:
            reasons.extend(self._errors or ["AkShare 当日市场广度或涨跌停池字段不完整。"])
        if verified:
            self._market_sources[analysis_date] = [EvidenceSource(
                "market-001",
                f"{config['index_name']}、全市场实时宽度与涨跌停池",
                "akshare_stock_zh_a_spot_em_stock_zt_pool_em",
                analysis_date,
                snapshot_ids=snapshot_ids,
            )]
        return MarketContext(
            index_name=config["index_name"],
            index_change_pct=index_change if verified else None,
            total_amount=total_amount if verified else None,
            advancers=advancers if verified else None,
            decliners=decliners if verified else None,
            limit_up_count=len(up_rows) if verified else None,
            limit_down_count=len(down_rows) if verified else None,
            hot_money_cycle="数据不足",
            policy_themes=[],
            failed_breakout_rate=failed_rate if verified else None,
            max_consecutive_boards=int(max(board_values, default=0)) if verified else None,
            first_board_count=(sum(value == float(market_rules["first_board_value"]) for value in board_values) if verified else None),
            sealed_limit_up_rate=sealed_rate if verified else None,
            one_price_limit_up_count=one_price_count if verified else None,
            broken_limit_up_count=len(broken_rows) if verified else None,
            board_ladder=board_ladder if verified else {},
            sentiment_history=[],
            data_status="verified" if verified else "insufficient",
            as_of=analysis_date if verified else None,
            unavailable_reasons=_unique_text(reasons),
        )

    def get_announcements(self, symbol: str, analysis_date: str) -> list[Announcement]:
        normalized = normalize_symbol(symbol)
        code = normalized.split(".")[0]
        config = load_runtime_settings().get("domain_knowledge", "announcement_timeliness")
        start = (date.fromisoformat(analysis_date) - timedelta(days=int(config["calendar_lookback_days"]))).strftime("%Y%m%d")
        rows: list[dict[str, Any]] = []
        announcement_calls_ok = True
        for market in self.config["announcement_markets"]:
            params = {
                "symbol": code,
                "market": market,
                "keyword": "",
                "category": "",
                "start_date": start,
                "end_date": analysis_date.replace("-", ""),
            }
            rows.extend(self._call("announcement", **params))
            announcement_calls_ok = announcement_calls_ok and self._last_call_succeeded("announcement", **params)
        items: list[Announcement] = []
        sources: list[EvidenceSource] = []
        for row in rows:
            row_code = _text(row, "代码")
            if row_code and row_code != code:
                continue
            title = _text(row, "公告标题")
            published_at = _date_text(row, "公告时间")
            if not title or not published_at or published_at > analysis_date:
                continue
            event_type, sentiment, priority = _announcement_classification(title, config)
            url = _text(row, "公告链接", "网址") or None
            source_id = "announcement-cninfo-" + hashlib.sha256(
                f"{code}|{published_at}|{title}|{url or ''}".encode("utf-8")
            ).hexdigest()[:12]
            items.append(Announcement(
                title=title,
                published_at=published_at,
                priority=priority,
                sentiment=sentiment,
                summary="巨潮资讯公告标题记录；正文条件需通过公告链接核验。",
                source_id=source_id,
                event_type=event_type,
                url=url,
            ))
            sources.append(EvidenceSource(
                source_id,
                f"{code} {title}",
                "akshare_cninfo_disclosure",
                published_at,
                url=url,
                snapshot_ids=self._snapshot_ids(("announcement",), normalized, analysis_date),
            ))
        items = list({item.source_id: item for item in items}.values())
        items, quality = validate_dataset_records(
            provider="akshare",
            dataset="announcements",
            records=items,
            analysis_date=analysis_date,
            snapshot_ids=self._snapshot_ids(("announcement",), normalized, analysis_date),
        )
        if not announcement_calls_ok:
            quality = replace(
                quality,
                status="failed",
                issues=[
                    *quality.issues,
                    DataQualityIssue(
                        code="provider_query_failed",
                        severity="error",
                        message="One or more CNInfo announcement queries failed; inquiry coverage is incomplete.",
                    ),
                ],
            )
        self._quality_reports[(normalized, analysis_date, "announcements")] = quality
        valid_ids = {item.source_id for item in items}
        if announcement_calls_ok:
            sources.append(EvidenceSource(
                "announcement-coverage-cninfo-001",
                f"{code} 巨潮资讯公告覆盖",
                "akshare_cninfo_disclosure",
                analysis_date,
                snapshot_ids=quality.snapshot_ids,
            ))
        self._announcement_sources[(normalized, analysis_date)] = list({
            item.id: item
            for item in sources
            if item.id in valid_ids or item.id == "announcement-coverage-cninfo-001"
        }.values())
        return items

    def get_evidence_sources(self, symbol: str, analysis_date: str) -> list[EvidenceSource]:
        return [
            *self._announcement_sources.get((normalize_symbol(symbol), analysis_date), []),
            *self._market_sources.get(analysis_date, []),
        ]

    def get_raw_snapshots(self, symbol: str, analysis_date: str) -> list[RawDataSnapshot]:
        normalized = normalize_symbol(symbol)
        return [item for item in self._raw_snapshots if snapshot_matches(item, normalized, analysis_date)]

    def get_data_quality_reports(self, symbol: str, analysis_date: str) -> list[DataQualityReport]:
        normalized = normalize_symbol(symbol)
        semantic = [
            report
            for (report_symbol, report_date, _), report in self._quality_reports.items()
            if report_symbol in {normalized, "__market__"} and report_date == analysis_date
        ]
        raw = [validate_raw_snapshot(item) for item in self.get_raw_snapshots(normalized, analysis_date)]
        return [*semantic, *raw]

    def get_intraday_snapshot(self, symbol: str, analysis_date: str) -> IntradaySnapshot:
        if analysis_date != self._today().isoformat():
            return IntradaySnapshot("unavailable", analysis_date, unavailable_reasons=["实时分时快照不能用于不同日期的历史分析。"])
        code = normalize_symbol(symbol).split(".")[0]
        config = load_runtime_settings().get("domain_knowledge", "intraday")
        rows = self._call(
            "minute", symbol=code, start_date=f"{analysis_date} 09:30:00",
            end_date=f"{analysis_date} 15:00:00", period=config["minute_period"], adjust="",
        )
        bars = [
            IntradayBar(
                _text(row, "时间", "日期", "day"), _number(row, "开盘"), _number(row, "最高"),
                _number(row, "最低"), _number(row, "收盘"), _number(row, "成交量"), _number(row, "成交额"),
            )
            for row in rows if _text(row, "时间", "日期", "day").startswith(analysis_date)
        ]
        bids, asks = _order_book_levels(self._call("order_book", symbol=code))
        source_ids = (["intraday-bars-akshare-001"] if bars else []) + (["order-book-akshare-001"] if bids or asks else [])
        return IntradaySnapshot(
            data_status="verified" if bars else "unavailable",
            as_of=bars[-1].timestamp if bars else analysis_date,
            bars=bars, bids=bids, asks=asks, source_ids=source_ids,
            unavailable_reasons=[] if bars else list(self._errors) or ["AkShare未返回当日分时数据。"],
        )

    def _northbound(self, code: str, analysis_date: str) -> NorthboundHoldingRecord | None:
        rows = self._call("northbound", market="北向", indicator="今日排行")
        row = next((item for item in rows if _text(item, "代码") == code), None)
        normalized = normalize_symbol(code)
        if not row:
            _, quality = validate_dataset_records(
                provider="akshare",
                dataset="northbound_holding",
                records=[],
                analysis_date=analysis_date,
                snapshot_ids=self._snapshot_ids(("northbound",), normalized, analysis_date),
            )
            self._quality_reports[(normalized, analysis_date, "northbound_holding")] = quality
            return None
        result = NorthboundHoldingRecord(
            analysis_date,
            _optional_number(row, "今日持股-股数"),
            _optional_number(row, "今日持股-市值"),
            _first_number_matching(row, "增持估计-股数"),
            "northbound-akshare-001",
        )
        valid, quality = validate_dataset_records(
            provider="akshare",
            dataset="northbound_holding",
            records=[result],
            analysis_date=analysis_date,
            snapshot_ids=self._snapshot_ids(("northbound",), normalized, analysis_date),
        )
        self._quality_reports[(normalized, analysis_date, "northbound_holding")] = quality
        return valid[0] if valid else None

    def _holder_trades(self, code: str, analysis_date: str) -> list[CorporateEvent]:
        normalized = normalize_symbol(code)
        if not self._enable_slow_bulk_queries:
            _, quality = validate_dataset_records(
                provider="akshare",
                dataset="holder_trades",
                records=[],
                analysis_date=analysis_date,
                snapshot_ids=[],
            )
            self._quality_reports[(normalized, analysis_date, "holder_trades")] = replace(
                quality,
                status="warning",
                issues=[
                    *quality.issues,
                    DataQualityIssue(
                        code="slow_bulk_query_disabled",
                        severity="warning",
                        message=(
                            "AkShare 全市场股东增减持查询已按运行配置关闭；"
                            "优先使用 Tushare 按标的接口，缺失时该风险保持未知。"
                        ),
                    ),
                ],
            )
            return []
        params = {"symbol": "全部"}
        snapshot_start = len(self._raw_snapshots)
        rows = self._call("holder_trade", **params)
        holder_snapshot_ids = [item.snapshot_id for item in self._raw_snapshots[snapshot_start:]]
        query_ok = self._last_call_succeeded("holder_trade", **params)
        config = load_runtime_settings().get("domain_knowledge", "risk_scanner")
        earliest = date.fromisoformat(analysis_date) - timedelta(days=int(config["holder_reduction_lookback_days"]))
        events: list[CorporateEvent] = []
        for row in rows:
            if _text(row, "代码") != code:
                continue
            published_at = _normalized_date(_text(row, "公告日", "公告日期", "变动截止日", "截止日期"))
            if not published_at or not earliest <= date.fromisoformat(published_at) <= date.fromisoformat(analysis_date):
                continue
            action = _text(row, "持股变动信息-增减", "变动方向", default="未知")
            impact = "negative" if "减" in action else "positive" if "增" in action else "neutral"
            events.append(CorporateEvent("股东增减持", f"股东{action}：{_text(row, '股东名称', default=code)}", published_at, impact, f"变动数量：{_text(row, '持股变动信息-变动数量', default='未披露')}", "holder-trade-akshare-001"))
        events, quality = validate_dataset_records(
            provider="akshare",
            dataset="holder_trades",
            records=events,
            analysis_date=analysis_date,
            snapshot_ids=holder_snapshot_ids,
        )
        if not query_ok:
            quality = replace(
                quality,
                status="failed",
                issues=[
                    *quality.issues,
                    DataQualityIssue(
                        code="provider_query_failed",
                        severity="error",
                        message="AkShare holder-trade query failed; reduction risk remains unavailable.",
                    ),
                ],
            )
        self._quality_reports[(normalized, analysis_date, "holder_trades")] = quality
        return events

    def _call(self, key: str, **kwargs: object) -> list[dict[str, Any]]:
        function_name = self.config["functions"][key]
        cached = self._cached_bulk_snapshot(key, kwargs)
        if cached is not None:
            snapshot, records = cached
            if all(item.snapshot_id != snapshot.snapshot_id for item in self._raw_snapshots):
                self._raw_snapshots.append(snapshot)
            self._call_outcomes.append((function_name, dict(kwargs), "success"))
            return records
        if self._client is None:
            message = "AkShare client is unavailable; install the optional package."
            self._errors.append(message)
            self._capture(function_name, kwargs, [], "error", message)
            self._call_outcomes.append((function_name, dict(kwargs), "error"))
            return []
        try:
            records = retry_call(
                lambda: _records(getattr(self._client, function_name)(**kwargs)),
                operation_name=f"AkShare {function_name}",
            )
            self._capture(function_name, kwargs, records, "success")
            self._call_outcomes.append((function_name, dict(kwargs), "success"))
            return records
        except Exception as exc:  # public endpoint failures are evidence unavailability, never neutral facts
            message = f"AkShare {function_name} unavailable: {exc}"
            self._errors.append(message)
            self._capture(function_name, kwargs, [], "error", message)
            self._call_outcomes.append((function_name, dict(kwargs), "error"))
            return []

    def _cached_bulk_snapshot(
        self,
        key: str,
        request_params: dict[str, object],
    ) -> tuple[RawDataSnapshot, list[dict[str, Any]]] | None:
        config = self.config.get("bulk_snapshot_cache", {})
        if key not in set(config.get("enabled_interfaces", [])):
            return None
        maximum_age = timedelta(minutes=float(config["maximum_age_minutes"]))
        interface = self.config["functions"][key]
        now = datetime.now(timezone.utc)
        candidates = [
            item
            for item in self._raw_store.list()
            if item.provider == "akshare"
            and item.interface == interface
            and item.status == "success"
            and not item.truncated
            and item.request_params == request_params
            and snapshot_is_intact(item)
        ]
        for snapshot in sorted(candidates, key=lambda item: item.requested_at, reverse=True):
            requested_at = datetime.fromisoformat(snapshot.requested_at)
            if requested_at.tzinfo is None:
                requested_at = requested_at.replace(tzinfo=timezone.utc)
            if timedelta(0) <= now - requested_at <= maximum_age:
                return snapshot, [dict(item) for item in snapshot.records]
        return None

    def _last_call_succeeded(self, key: str, **expected_params: object) -> bool:
        function_name = self.config["functions"][key]
        for interface, params, status in reversed(self._call_outcomes):
            if interface == function_name and all(params.get(name) == value for name, value in expected_params.items()):
                return status == "success"
        return False

    def _capture(
        self,
        interface: str,
        params: dict[str, object],
        records: list[dict[str, Any]],
        status: str,
        error: str | None = None,
    ) -> None:
        if not load_runtime_settings().get("data_quality", "raw_snapshots", "enabled"):
            return
        snapshot = build_raw_snapshot(
            provider="akshare",
            interface=interface,
            request_params=params,
            records=records,
            status=status,
            error=error,
        )
        self._raw_store.save(snapshot)
        self._raw_snapshots.append(snapshot)

    def _snapshot_ids(
        self,
        interfaces: tuple[str, ...],
        symbol: str,
        analysis_date: str,
    ) -> list[str]:
        function_names = {self.config["functions"][item] for item in interfaces}
        return [
            item.snapshot_id
            for item in self.get_raw_snapshots(symbol, analysis_date)
            if item.interface in function_names
        ]

    def _market_snapshot_ids(self, analysis_date: str) -> list[str]:
        function_names = {
            self.config["functions"][key]
            for key in ("market_spot", "index_spot", "limit_up", "limit_down", "limit_broken")
        }
        return [
            item.snapshot_id
            for item in self._raw_snapshots
            if item.interface in function_names and item.analysis_date in {None, analysis_date}
        ]

    def _build_client(self) -> AkshareClient | None:
        if not self.config["enabled"]:
            return None
        try:
            import akshare
        except ImportError:
            return None
        return akshare


def _records(table: object) -> list[dict[str, Any]]:
    if table is None:
        return []
    if isinstance(table, list):
        return [dict(item) for item in table if isinstance(item, dict)]
    to_dict = getattr(table, "to_dict", None)
    if callable(to_dict):
        return [dict(item) for item in to_dict("records")]
    raise TypeError("AkShare response must be a DataFrame-like object or record list")


def _text(row: dict[str, Any], key: str, *alternatives: str, default: str = "") -> str:
    for candidate in (key, *alternatives):
        value = row.get(candidate)
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


def _first_number_matching(row: dict[str, Any], fragment: str) -> float | None:
    key = next((item for item in row if fragment in item), None)
    return _optional_number(row, key) if key else None


def _date_text(row: dict[str, Any], key: str) -> str:
    value = _text(row, key)
    return value[:10]


def _normalized_date(value: str) -> str:
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return ""


def _configured_board_ladder(
    rows: list[dict[str, Any]],
    board_count_field: str,
    buckets: list[dict[str, object]],
) -> dict[str, int]:
    result: dict[str, int] = {}
    for bucket in buckets:
        minimum = int(bucket["minimum"])
        maximum = bucket.get("maximum")
        result[str(bucket["label"])] = sum(
            value is not None
            and value >= minimum
            and (maximum is None or value <= int(maximum))
            for value in (_optional_number(row, board_count_field) for row in rows)
        )
    return result


def _unique_text(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def _order_book_levels(rows: list[dict[str, Any]]) -> tuple[list[OrderBookLevel], list[OrderBookLevel]]:
    flat: dict[str, object] = {}
    for row in rows:
        item = _text(row, "item", "项目", "指标")
        if item:
            flat[item.lower()] = row.get("value", row.get("数值", row.get("值")))
        else:
            flat.update({str(key).lower(): value for key, value in row.items()})
    bids: list[OrderBookLevel] = []
    asks: list[OrderBookLevel] = []
    depth = load_runtime_settings().get("domain_knowledge", "intraday", "order_book_depth")
    for index in range(1, depth + 1):
        bid_price = _lookup_number(flat, f"buy_{index}", f"买{index}", f"买{index}价")
        bid_volume = _lookup_number(flat, f"buy_{index}_vol", f"buy_{index}_volume", f"买{index}量")
        ask_price = _lookup_number(flat, f"sell_{index}", f"卖{index}", f"卖{index}价")
        ask_volume = _lookup_number(flat, f"sell_{index}_vol", f"sell_{index}_volume", f"卖{index}量")
        if bid_price is not None and bid_volume is not None:
            bids.append(OrderBookLevel(bid_price, bid_volume))
        if ask_price is not None and ask_volume is not None:
            asks.append(OrderBookLevel(ask_price, ask_volume))
    return bids, asks


def _lookup_number(values: dict[str, object], *keys: str) -> float | None:
    for key in keys:
        value = values.get(key.lower())
        try:
            if value not in {None, "", "-", "--"}:
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _announcement_classification(title: str, config: dict[str, Any]) -> tuple[str, str, str]:
    is_reply = any(keyword in title for keyword in config["reply_keywords"])
    is_inquiry = any(keyword in title for keyword in config["inquiry_keywords"])
    event_type = "inquiry_reply" if is_reply and is_inquiry else "inquiry" if is_inquiry else "general"
    if any(keyword in title for keyword in config["negative_title_keywords"]) and event_type != "inquiry_reply":
        sentiment = "negative"
    elif any(keyword in title for keyword in config["positive_title_keywords"]):
        sentiment = "positive"
    else:
        sentiment = "neutral"
    return event_type, sentiment, "exchange" if is_inquiry else "company"
