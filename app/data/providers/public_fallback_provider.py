from __future__ import annotations

import json
import math
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import date, timedelta
from typing import Any, Callable
from urllib.error import URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from app.config.runtime import load_runtime_settings
from app.data.providers.base import MarketDataProvider, ProviderCapabilities
from app.data.quality import validate_dataset_records
from app.data.raw_snapshots import InMemoryRawSnapshotStore, RawDataSnapshot, RawSnapshotStore, build_raw_snapshot
from app.indicators.market_breadth import calculate_market_breadth_facts
from app.network.retry import retry_call
from app.rules.trading_rules import daily_limit_pct, infer_board, normalize_symbol
from app.schemas.report import (
    Announcement,
    DailyPrice,
    DataQualityIssue,
    DataQualityReport,
    EvidenceSource,
    FundamentalSnapshot,
    MarketContext,
    MoneyFlowSnapshot,
    StockProfile,
)


FetchText = Callable[[str], str]


class PublicFallbackMarketDataProvider(MarketDataProvider):
    """Independent public fallbacks: Tencent prices, Sina facts, THS flow.

    The adapter intentionally leaves unsupported fields empty. It never turns
    price/volume proxies into institutional money-flow facts.
    """

    def __init__(
        self,
        client: object | None = None,
        fetch_text: FetchText | None = None,
        raw_store: RawSnapshotStore | None = None,
        today: Callable[[], date] | None = None,
    ) -> None:
        self.config = load_runtime_settings().get("providers", "public_fallback")
        self._client = client or self._build_client()
        self._fetch_text = fetch_text or _fetch_text
        self._raw_store = raw_store or InMemoryRawSnapshotStore()
        self._today = today or date.today
        self._raw: list[RawDataSnapshot] = []
        self._quality: dict[tuple[str, str, str], DataQualityReport] = {}
        self._evidence: dict[tuple[str, str], list[EvidenceSource]] = {}
        self._tencent_cache: dict[tuple[str, str, int], dict[str, Any]] = {}
        self._fundamental_cache: dict[tuple[str, str], FundamentalSnapshot] = {}
        self._flow_rows: dict[str, list[dict[str, Any]]] = {}
        self._market_cache: dict[str, MarketContext] = {}

    def get_provider_capabilities(self) -> list[ProviderCapabilities]:
        return [ProviderCapabilities(
            provider="public_fallback",
            datasets=frozenset({"stock_profile", "daily_prices", "fundamentals", "money_flow", "market_context", "raw_snapshots", "data_quality"}),
            persists_raw_snapshots=True,
        )]

    def get_stock_profile(self, symbol: str) -> StockProfile:
        normalized = normalize_symbol(symbol)
        payload = self._tencent_payload(normalized, self._today().isoformat(), 2)
        quote = _tencent_quote(payload, normalized)
        name = str(quote[1]).strip() if len(quote) > 1 and str(quote[1]).strip() else normalized
        return StockProfile(
            symbol=normalized,
            name=name,
            industry="未知",
            board=infer_board(normalized),
            is_st=name.upper().startswith(("ST", "*ST")),
        )

    def get_daily_prices(self, symbol: str, analysis_date: str, lookback_days: int) -> list[DailyPrice]:
        normalized = normalize_symbol(symbol)
        payload = self._tencent_payload(normalized, analysis_date, lookback_days)
        rows = _tencent_kline_rows(payload, normalized)
        prices = [
            DailyPrice(
                trade_date=str(row[0]),
                open=_required_float(row[1]),
                close=_required_float(row[2]),
                high=_required_float(row[3]),
                low=_required_float(row[4]),
                volume=_required_float(row[5]),
                amount=None,
                turnover_rate=None,
            )
            for row in rows
            if isinstance(row, list) and len(row) >= 6 and str(row[0]) <= analysis_date
        ][-lookback_days:]
        snapshot_ids = self._snapshot_ids("tencent_kline", normalized, analysis_date)
        prices, quality = validate_dataset_records(
            provider="tencent",
            dataset="daily_prices",
            records=prices,
            analysis_date=analysis_date,
            snapshot_ids=snapshot_ids,
        )
        quality_key = (normalized, analysis_date, "daily_prices")
        existing_quality = self._quality.get(quality_key)
        if existing_quality is None or quality.checked_records >= existing_quality.checked_records:
            self._quality[quality_key] = quality
        if prices:
            self._record_evidence(normalized, analysis_date, EvidenceSource(
                "price-001", f"{normalized} 腾讯历史行情", "tencent_ifzq_kline", prices[-1].trade_date,
                snapshot_ids=snapshot_ids,
            ))
        return prices

    def get_fundamentals(self, symbol: str, analysis_date: str | None = None) -> FundamentalSnapshot:
        normalized = normalize_symbol(symbol)
        effective_date = analysis_date or self._today().isoformat()
        cache_key = (normalized, effective_date)
        if cache_key in self._fundamental_cache:
            return self._fundamental_cache[cache_key]
        rows, error = self._call_dataframe_result(
            self.config["fundamental_function"], symbol=normalized.split(".")[0]
        )
        snapshot = _fundamentals_from_sina(rows, effective_date, self.config["financial_metrics"])
        raw_error = error or (None if snapshot.statement_as_of else "provider returned no usable financial statement")
        raw = self._save_raw(
            "sina", self.config["fundamental_function"],
            {"symbol": normalized, "end_date": effective_date}, rows, raw_error,
        )
        if snapshot.statement_as_of:
            quality_fields = list(self.config["fundamental_quality_fields"])
            missing_fields = [name for name in quality_fields if getattr(snapshot, name, None) is None]
            self._quality[(normalized, effective_date, "fundamentals_public")] = DataQualityReport(
                provider="sina",
                dataset="fundamentals_public",
                status="warning" if missing_fields else "passed",
                checked_records=1,
                valid_records=1,
                completeness=round((len(quality_fields) - len(missing_fields)) / max(1, len(quality_fields)), 4),
                as_of=snapshot.statement_as_of,
                snapshot_ids=[raw.snapshot_id],
                issues=[
                    DataQualityIssue(
                        code="financial_field_unavailable",
                        severity="warning",
                        message=f"新浪财务摘要缺少 {name}；相关拆解保持数据不足。",
                        field=name,
                    )
                    for name in missing_fields
                ],
                blocking=False,
            )
            self._record_evidence(normalized, effective_date, EvidenceSource(
                "fund-001", f"{normalized} 新浪财务摘要", "sina_financial_abstract",
                snapshot.statement_as_of, snapshot_ids=[raw.snapshot_id],
            ))
        if snapshot.statement_as_of:
            self._fundamental_cache[cache_key] = snapshot
        return snapshot

    def get_money_flow(self, symbol: str, analysis_date: str) -> MoneyFlowSnapshot:
        normalized = normalize_symbol(symbol)
        fields = self.config["money_flow_fields"]
        code = normalized.split(".")[0]
        prices = self.get_daily_prices(normalized, analysis_date, 2)
        as_of = prices[-1].trade_date if prices else None
        rows = self._flow_rows.get(analysis_date, [])
        row = _find_flow_row(rows, fields["code"], code)
        if row is None:
            rows, error = self._call_dataframe_result(
                self.config["money_flow_function"], symbol=self.config["money_flow_period"]
            )
            row = _find_flow_row(rows, fields["code"], code)
            lookup_error = error or (
                None if row is not None else f"target {code} absent from provider coverage ({len(rows)} rows)"
            )
            self._save_raw(
                "ths", self.config["money_flow_function"],
                {"trade_date": analysis_date, "symbol": normalized}, rows, lookup_error,
            )
            if row is not None:
                self._flow_rows[analysis_date] = rows
        if row is None or as_of is None:
            return self._money_flow_from_sina_ticks(normalized, analysis_date, as_of)
        main = _amount(row.get(fields["net"]), self.config["amount_units"])
        turnover = _percent(row.get(fields["turnover_rate"]))
        if main is None:
            return self._money_flow_from_sina_ticks(normalized, analysis_date, as_of)
        self._record_evidence(normalized, analysis_date, EvidenceSource(
            "flow-001", f"{normalized} 同花顺个股资金流", "ths_individual_fund_flow", as_of,
            snapshot_ids=self._snapshot_ids(self.config["money_flow_function"], normalized, analysis_date),
        ))
        return MoneyFlowSnapshot(
            main_net_inflow=main,
            super_large_net_inflow=None,
            margin_balance_change=None,
            northbound_signal="数据不足",
            turnover_rate=turnover,
            block_trade_signal="数据不足",
            as_of=as_of,
            flow_method="vendor_main_net_flow",
        )

    def _money_flow_from_sina_ticks(
        self, symbol: str, analysis_date: str, price_as_of: str | None
    ) -> MoneyFlowSnapshot:
        """Use observable tick direction without inventing main-capital flow."""
        if price_as_of is None or price_as_of != analysis_date:
            return _empty_flow(price_as_of)
        rows, error = self._call_dataframe_result(
            self.config["sina_tick_function"],
            symbol=_tencent_code(symbol),
            date=analysis_date.replace("-", ""),
        )
        fields = self.config["sina_tick_fields"]
        minimum_time = str(self.config["sina_tick_minimum_time"])
        usable = [
            row for row in rows
            if str(row.get(fields["time"], "")) >= minimum_time
            and _optional_float(row.get(fields["price"])) is not None
            and _optional_float(row.get(fields["volume"])) is not None
            and (_optional_float(row.get(fields["previous_price"])) or 0) > 0
        ]
        up_code = str(self.config["sina_tick_direction_codes"]["up"])
        down_code = str(self.config["sina_tick_direction_codes"]["down"])

        def amount(row: dict[str, Any]) -> float:
            return float(row[fields["price"]]) * float(row[fields["volume"]])

        up_amount = sum(amount(row) for row in usable if str(row.get(fields["direction"])) == up_code)
        down_amount = sum(amount(row) for row in usable if str(row.get(fields["direction"])) == down_code)
        gross_amount = sum(amount(row) for row in usable)
        raw_error = error or (None if usable else "provider returned no usable post-open tick records")
        raw = self._save_raw(
            "sina", self.config["sina_tick_function"],
            {"symbol": symbol, "trade_date": analysis_date}, rows, raw_error,
        )
        if not usable:
            return _empty_flow(price_as_of)
        self._quality[(symbol, analysis_date, "money_flow_tick_direction")] = DataQualityReport(
            provider="sina",
            dataset="money_flow_tick_direction",
            status="warning",
            checked_records=len(rows),
            valid_records=len(usable),
            completeness=round(len(usable) / len(rows), 4) if rows else 0.0,
            as_of=analysis_date,
            snapshot_ids=[raw.snapshot_id],
            issues=[DataQualityIssue(
                "methodology_scope", "warning",
                "逐笔价格方向净额不等同于供应商定义的主力资金净流入，仅用于验证成交方向。",
            )],
            blocking=False,
        )
        self._record_evidence(symbol, analysis_date, EvidenceSource(
            "flow-001",
            f"{symbol} 新浪逐笔成交价格方向净额（非主力资金口径）",
            "sina_tick_trade_direction",
            analysis_date,
            snapshot_ids=[raw.snapshot_id],
        ))
        return MoneyFlowSnapshot(
            main_net_inflow=None,
            super_large_net_inflow=None,
            margin_balance_change=None,
            northbound_signal="数据不足",
            turnover_rate=None,
            block_trade_signal="数据不足",
            as_of=analysis_date,
            trade_direction_net_inflow=up_amount - down_amount,
            trade_direction_gross_amount=gross_amount,
            flow_method="tick_price_direction",
        )

    def get_sina_tick_money_flow(self, symbol: str, analysis_date: str) -> MoneyFlowSnapshot:
        """Bypass a failed THS circuit and use the independent tick route."""
        normalized = normalize_symbol(symbol)
        prices = self.get_daily_prices(normalized, analysis_date, 2)
        as_of = prices[-1].trade_date if prices else None
        return self._money_flow_from_sina_ticks(normalized, analysis_date, as_of)

    def get_announcements(self, symbol: str, analysis_date: str) -> list[Announcement]:
        return []

    def get_market_context(self, analysis_date: str) -> MarketContext:
        cached_context = self._market_cache.get(analysis_date)
        if cached_context is not None and cached_context.data_status == "verified":
            return cached_context
        self._market_cache.pop(analysis_date, None)
        if analysis_date != self._today().isoformat():
            return _empty_market(analysis_date, "新浪全市场列表是当前截面，不能回填历史日期。")
        try:
            total = self._sina_market_count()
            rows = self._sina_market_rows(total)
            valid = [item for item in rows if _optional_float(item.get("settlement")) not in {None, 0}]
            actively_quoted = [item for item in valid if _optional_float(item.get("trade")) not in {None, 0}]
            minimum = math.ceil(total * float(self.config["sina_market_minimum_coverage"]))
            if len(actively_quoted) < minimum:
                context = _empty_market(
                    analysis_date,
                    f"新浪全市场有效报价仅 {len(actively_quoted)}/{total}，未达到配置覆盖率。",
                )
                self._market_cache[analysis_date] = context
                return context
            index_payload = self._tencent_payload_for_code(self.config["tencent_index_symbol"], analysis_date, 2)
            index_quote = _tencent_quote_by_code(index_payload, self.config["tencent_index_symbol"])
            pct_index = int(self.config["tencent_quote_change_pct_index"])
            index_change = _optional_float(index_quote[pct_index]) if len(index_quote) > pct_index else None
            advancers = sum((_optional_float(item.get("changepercent")) or 0) > 0 for item in actively_quoted)
            decliners = sum((_optional_float(item.get("changepercent")) or 0) < 0 for item in actively_quoted)
            total_amount = sum(_optional_float(item.get("amount")) or 0 for item in actively_quoted)
            pct_changes = [float(_optional_float(item.get("changepercent")) or 0) for item in actively_quoted]
            amounts = [float(_optional_float(item.get("amount")) or 0) for item in actively_quoted]
            breadth_config = load_runtime_settings().get("domain_knowledge", "market_breadth_confirmation")
            breadth_facts = calculate_market_breadth_facts(
                pct_changes,
                amounts,
                top_amount_count=int(breadth_config["top_amount_count"]),
            )
            limit_structure = _market_limit_structure(
                actively_quoted,
                tolerance=float(self.config["limit_match_tolerance_pct"]),
            )
            limit_up = limit_structure["sealed"]
            limit_down = sum(_is_at_limit(item, positive=False, tolerance=float(self.config["limit_match_tolerance_pct"])) for item in actively_quoted)
            touched_up = limit_structure["sealed"] + limit_structure["broken"]
            failed_rate = limit_structure["broken"] / touched_up * 100 if touched_up else None
            sealed_rate = limit_structure["sealed"] / touched_up * 100 if touched_up else None
            raw_ids = self._snapshot_ids("sina_market_list", None, analysis_date)
            context = MarketContext(
                index_name="上证指数",
                index_change_pct=index_change,
                total_amount=total_amount,
                advancers=advancers,
                decliners=decliners,
                limit_up_count=limit_up,
                limit_down_count=limit_down,
                hot_money_cycle="数据不足",
                policy_themes=[],
                failed_breakout_rate=failed_rate,
                sealed_limit_up_rate=sealed_rate,
                one_price_limit_up_count=limit_structure["one_price"],
                broken_limit_up_count=limit_structure["broken"],
                median_stock_change_pct=breadth_facts.median_stock_change_pct,
                amount_weighted_change_pct=breadth_facts.amount_weighted_change_pct,
                top_amount_concentration_pct=breadth_facts.top_amount_concentration_pct,
                data_status="verified",
                as_of=analysis_date,
                unavailable_reasons=["新浪当前截面可由最高价与现价核验触板/炸板，但不含连板梯队和连续情绪历史；周期维度保持数据不足。"],
            )
            self._quality[("__market__", analysis_date, "market_breadth_public")] = DataQualityReport(
                provider="sina",
                dataset="market_breadth_public",
                status="warning",
                checked_records=total,
                valid_records=len(actively_quoted),
                completeness=round(len(actively_quoted) / total, 4),
                as_of=analysis_date,
                snapshot_ids=raw_ids,
                issues=[DataQualityIssue("partial_market_structure", "warning", "备用源可核验当日触板/炸板，但不含连板梯队和连续情绪历史。")],
                blocking=False,
            )
            self._record_evidence("__market__", analysis_date, EvidenceSource(
                "market-001", "新浪全 A 股市场宽度与腾讯上证指数", "sina_market_center+tencent_index",
                analysis_date, snapshot_ids=raw_ids,
            ))
            self._market_cache[analysis_date] = context
            return context
        except (OSError, URLError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            context = _empty_market(analysis_date, f"公共市场宽度备用源失败：{exc}")
            self._market_cache[analysis_date] = context
            return context

    def get_evidence_sources(self, symbol: str, analysis_date: str) -> list[EvidenceSource]:
        normalized = normalize_symbol(symbol) if symbol != "__market__" else symbol
        return [
            *self._evidence.get((normalized, analysis_date), []),
            *self._evidence.get(("__market__", analysis_date), []),
        ]

    def get_raw_snapshots(self, symbol: str, analysis_date: str) -> list[RawDataSnapshot]:
        normalized = normalize_symbol(symbol)
        return [item for item in self._raw if item.analysis_date in {None, analysis_date} and item.symbol in {None, normalized}]

    def get_data_quality_reports(self, symbol: str, analysis_date: str) -> list[DataQualityReport]:
        normalized = normalize_symbol(symbol)
        return [
            report for (report_symbol, report_date, _), report in self._quality.items()
            if report_date == analysis_date and report_symbol in {normalized, "__market__"}
        ]

    def _tencent_payload(self, symbol: str, analysis_date: str, lookback_days: int) -> dict[str, Any]:
        code = _tencent_code(symbol)
        key = (code, analysis_date, lookback_days)
        cached = self._tencent_cache.get(key)
        if cached:
            return cached
        payload = self._tencent_payload_for_code(code, analysis_date, lookback_days)
        if payload:
            self._tencent_cache[key] = payload
        return payload

    def _tencent_payload_for_code(self, code: str, analysis_date: str, lookback_days: int) -> dict[str, Any]:
        params = {"param": f"{code},day,,,{max(2, lookback_days)},qfq"}
        url = self.config["tencent_kline_url"] + "?" + urlencode(params)
        try:
            raw = retry_call(lambda: self._fetch_text(url), operation_name="Tencent K-line fallback")
            payload = json.loads(raw)
            if not isinstance(payload, dict) or int(payload.get("code", -1)) != 0:
                raise ValueError("Tencent K-line payload is invalid")
            self._save_raw("tencent", "tencent_kline", {"symbol": _normalized_from_tencent(code), "provider_symbol": code, "end_date": analysis_date}, [payload], None)
            return payload
        except (OSError, URLError, ValueError, TypeError, json.JSONDecodeError) as exc:
            self._save_raw("tencent", "tencent_kline", {"symbol": _normalized_from_tencent(code), "provider_symbol": code, "end_date": analysis_date}, [], str(exc))
            return {}

    def _sina_market_count(self) -> int:
        url = self.config["sina_market_count_url"] + "?" + urlencode({"node": self.config["sina_market_node"]})
        raw = retry_call(lambda: self._fetch_text(url), operation_name="Sina market count fallback")
        return int(str(json.loads(raw)))

    def _sina_market_rows(self, total: int) -> list[dict[str, Any]]:
        page_size = int(self.config["sina_market_page_size"])
        pages = math.ceil(total / page_size)
        with ThreadPoolExecutor(max_workers=int(self.config["sina_market_max_workers"]), thread_name_prefix="sina-market") as executor:
            batches = list(executor.map(self._sina_market_page, range(1, pages + 1)))
        rows = [item for batch in batches for item in batch]
        self._save_raw("sina", "sina_market_list", {"trade_date": self._today().isoformat()}, rows, None)
        return rows

    def _sina_market_page(self, page: int) -> list[dict[str, Any]]:
        params = {
            "page": page, "num": self.config["sina_market_page_size"], "sort": "symbol", "asc": 1,
            "node": self.config["sina_market_node"], "symbol": "", "_s_r_a": "page",
        }
        url = self.config["sina_market_list_url"] + "?" + urlencode(params)
        raw = retry_call(lambda: self._fetch_text(url), operation_name="Sina market list fallback")
        payload = json.loads(raw)
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []

    def _call_dataframe(self, function_name: str, **kwargs: object) -> list[dict[str, Any]]:
        return self._call_dataframe_result(function_name, **kwargs)[0]

    def _call_dataframe_result(
        self, function_name: str, **kwargs: object
    ) -> tuple[list[dict[str, Any]], str | None]:
        if self._client is None:
            return [], "AkShare client is unavailable"
        try:
            frame = retry_call(lambda: getattr(self._client, function_name)(**kwargs), operation_name=f"AkShare {function_name}")
            if hasattr(frame, "to_dict"):
                return list(frame.to_dict(orient="records")), None
            return list(frame or []), None
        except Exception as exc:
            return [], str(exc)[:500]

    def _save_raw(
        self,
        provider: str,
        interface: str,
        params: dict[str, object],
        records: list[dict[str, Any]],
        error: str | None,
    ) -> RawDataSnapshot:
        snapshot = build_raw_snapshot(
            provider=provider,
            interface=interface,
            request_params=params,
            records=records,
            status="failed" if error else "success",
            error=error,
        )
        self._raw.append(snapshot)
        self._raw_store.save(snapshot)
        return snapshot

    def _snapshot_ids(self, interface: str, symbol: str | None, analysis_date: str) -> list[str]:
        normalized = normalize_symbol(symbol) if symbol and symbol[0].isdigit() else symbol
        return [
            item.snapshot_id for item in self._raw
            if item.interface == interface and item.analysis_date in {None, analysis_date} and item.symbol in {None, normalized, symbol}
        ]

    def _record_evidence(self, symbol: str, analysis_date: str, source: EvidenceSource) -> None:
        key = (symbol, analysis_date)
        current = {item.id: item for item in self._evidence.get(key, [])}
        current[source.id] = source
        self._evidence[key] = list(current.values())

    @staticmethod
    def _build_client() -> object | None:
        try:
            import akshare as ak  # type: ignore
            return ak
        except ImportError:
            return None


def _fetch_text(url: str) -> str:
    config = load_runtime_settings().get("providers", "public_fallback")
    allowed = [config["tencent_kline_url"], config["sina_market_count_url"], config["sina_market_list_url"]]
    if not any(url.startswith(item) for item in allowed):
        raise ValueError("Blocked public fallback URL")
    if config["curl_first"]:
        return _fetch_text_with_curl(url, config)
    request = Request(url, headers=config["headers"])
    try:
        with urlopen(request, timeout=load_runtime_settings().get("runtime", "network_timeout_seconds")) as response:
            body = response.read().decode("utf-8", errors="replace")
            if not body.strip():
                raise OSError("provider returned empty body")
            return body
    except (OSError, URLError):
        return _fetch_text_with_curl(url, config)


def _fetch_text_with_curl(url: str, config: dict[str, Any]) -> str:
    curl = shutil.which("curl")
    if not curl:
        raise OSError("curl is unavailable")
    headers = [arg for name, value in config["headers"].items() for arg in ("-H", f"{name}: {value}")]
    completed = subprocess.run(
        [curl, "--http1.1", "-sS", *headers, url], capture_output=True, text=True, check=False,
        timeout=load_runtime_settings().get("runtime", "network_timeout_seconds"),
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise OSError((completed.stderr or "curl returned no data").strip())
    return completed.stdout


def _tencent_code(symbol: str) -> str:
    code, exchange = normalize_symbol(symbol).split(".", 1)
    prefix = {"SH": "sh", "SZ": "sz", "BJ": "bj"}.get(exchange)
    if prefix is None:
        raise ValueError(f"Unsupported Tencent market: {exchange}")
    return prefix + code


def _normalized_from_tencent(code: str) -> str:
    prefix = code[:2].lower()
    exchange = {"sh": "SH", "sz": "SZ", "bj": "BJ"}.get(prefix)
    if exchange is None:
        return code.upper()
    return f"{code[2:]}.{exchange}"


def _tencent_data(payload: dict[str, Any], code: str) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return {}
    value = data.get(code)
    return value if isinstance(value, dict) else {}


def _tencent_kline_rows(payload: dict[str, Any], symbol: str) -> list[list[Any]]:
    data = _tencent_data(payload, _tencent_code(symbol))
    rows = data.get("qfqday") or data.get("day") or []
    return [item for item in rows if isinstance(item, list)] if isinstance(rows, list) else []


def _tencent_quote(payload: dict[str, Any], symbol: str) -> list[Any]:
    return _tencent_quote_by_code(payload, _tencent_code(symbol))


def _tencent_quote_by_code(payload: dict[str, Any], code: str) -> list[Any]:
    quote = _tencent_data(payload, code).get("qt")
    if not isinstance(quote, dict):
        return []
    value = quote.get(code)
    return value if isinstance(value, list) else []


def _fundamentals_from_sina(rows: list[dict[str, Any]], analysis_date: str, names: dict[str, str]) -> FundamentalSnapshot:
    if not rows:
        return _empty_fundamentals()
    indicator_field = next((key for key in rows[0] if key == "指标"), None)
    if indicator_field is None:
        return _empty_fundamentals()
    columns = sorted(
        (key for key in rows[0] if str(key).isdigit() and len(str(key)) == 8 and str(key) <= analysis_date.replace("-", "")),
        reverse=True,
    )
    if not columns:
        return _empty_fundamentals()
    current = columns[0]
    prior = str(int(current[:4]) - 1) + current[4:]
    by_name = {str(row.get(indicator_field)): row for row in rows}

    def value(name: str, period: str = current) -> float | None:
        row = by_name.get(names[name], {})
        return _optional_float(row.get(period))

    revenue = value("revenue")
    net_income = value("net_income")
    deducted_net_income = value("deducted_net_income")
    operating = value("operating_cash_flow")
    assets = value("total_assets")
    equity = value("total_equity")
    goodwill = value("goodwill")
    direct_asset_turnover = value("asset_turnover")
    direct_equity_multiplier = value("equity_multiplier")
    prior_revenue = value("revenue", prior)
    prior_income = value("net_income", prior)
    non_recurring_impact = (
        net_income - deducted_net_income
        if net_income is not None and deducted_net_income is not None
        else None
    )
    non_recurring_ratio = (
        non_recurring_impact / abs(net_income) * 100
        if non_recurring_impact is not None and net_income not in {None, 0}
        else None
    )
    limitations = [
        "新浪财务摘要不包含完整财报附注，异常项目仍需核验财报原文或问询回复。",
        "行业周期需由行业景气度数据独立验证，不能从单公司财务摘要推断。",
    ]
    if deducted_net_income is None:
        limitations.append("缺少扣非净利润，无法量化一次性损益对归母净利润的影响。")
    return FundamentalSnapshot(
        revenue_growth_yoy=_growth(revenue, prior_revenue),
        profit_growth_yoy=_growth(net_income, prior_income),
        roe=value("roe"),
        gross_margin=value("gross_margin"),
        debt_to_asset=value("debt_to_asset"),
        pe_ttm=None,
        pb=None,
        cashflow_quality=(operating / net_income) if operating is not None and net_income not in {None, 0} else None,
        forecast_revision="数据不足",
        revenue=revenue,
        net_income=net_income,
        operating_cash_flow=operating,
        total_assets=assets,
        total_equity=equity,
        statement_as_of=f"{current[:4]}-{current[4:6]}-{current[6:]}",
        net_profit_margin=(net_income / revenue) if net_income is not None and revenue not in {None, 0} else None,
        asset_turnover=(
            direct_asset_turnover
            if direct_asset_turnover is not None
            else (revenue / assets) if revenue is not None and assets not in {None, 0} else None
        ),
        equity_multiplier=(
            direct_equity_multiplier
            if direct_equity_multiplier is not None
            else (assets / equity) if assets is not None and equity not in {None, 0} else None
        ),
        goodwill_ratio=(goodwill / equity * 100) if goodwill is not None and equity not in {None, 0} else None,
        goodwill_as_of=f"{current[:4]}-{current[4:6]}-{current[6:]}" if goodwill is not None else None,
        goodwill_source_id="fund-001" if goodwill is not None else None,
        deducted_net_income=deducted_net_income,
        non_recurring_profit_impact=non_recurring_impact,
        non_recurring_profit_ratio=non_recurring_ratio,
        scope_limitations=limitations,
    )


def _is_at_limit(row: dict[str, Any], *, positive: bool, tolerance: float) -> bool:
    pct = _optional_float(row.get("changepercent"))
    if pct is None:
        return False
    symbol = str(row.get("symbol") or row.get("code") or "")
    code = "".join(character for character in symbol if character.isdigit())[-6:]
    if len(code) != 6:
        return False
    profile = StockProfile(normalize_symbol(code), str(row.get("name") or code), "未知", infer_board(normalize_symbol(code)), str(row.get("name") or "").upper().startswith(("ST", "*ST")))
    limit = float(daily_limit_pct(profile))
    expected = limit if positive else -limit
    return abs(pct - expected) <= tolerance


def _market_limit_structure(rows: list[dict[str, Any]], *, tolerance: float) -> dict[str, int]:
    sealed = 0
    broken = 0
    one_price = 0
    for row in rows:
        is_sealed = _is_at_limit(row, positive=True, tolerance=tolerance)
        touched = _field_at_upper_limit(row, "high", tolerance=tolerance)
        if is_sealed:
            sealed += 1
            if all(
                _field_at_upper_limit(row, field, tolerance=tolerance)
                for field in ("open", "high", "low", "trade")
            ):
                one_price += 1
        elif touched:
            broken += 1
    return {"sealed": sealed, "broken": broken, "one_price": one_price}


def _field_at_upper_limit(row: dict[str, Any], field: str, *, tolerance: float) -> bool:
    value = _optional_float(row.get(field))
    settlement = _optional_float(row.get("settlement"))
    if value is None or settlement in {None, 0}:
        return False
    pct = (value / settlement - 1) * 100
    symbol = str(row.get("symbol") or row.get("code") or "")
    code = "".join(character for character in symbol if character.isdigit())[-6:]
    if len(code) != 6:
        return False
    normalized = normalize_symbol(code)
    name = str(row.get("name") or code)
    profile = StockProfile(
        normalized,
        name,
        "未知",
        infer_board(normalized),
        name.upper().startswith(("ST", "*ST")),
    )
    return abs(pct - float(daily_limit_pct(profile))) <= tolerance


def _empty_fundamentals() -> FundamentalSnapshot:
    return FundamentalSnapshot(None, None, None, None, None, None, None, None, "数据不足")


def _find_flow_row(
    rows: list[dict[str, Any]], code_field: str, requested_code: str
) -> dict[str, Any] | None:
    for item in rows:
        raw_code = str(item.get(code_field, "")).strip().split(".")[0]
        digits = "".join(character for character in raw_code if character.isdigit())
        if digits[-6:].zfill(6) == requested_code:
            return item
    return None


def _empty_flow(as_of: str | None) -> MoneyFlowSnapshot:
    return MoneyFlowSnapshot(None, None, None, "数据不足", None, "数据不足", as_of=as_of)


def _empty_market(analysis_date: str, reason: str) -> MarketContext:
    return MarketContext("上证指数", None, None, None, None, None, None, "数据不足", [], data_status="unavailable", as_of=None, unavailable_reasons=[reason])


def _amount(value: object, units: dict[str, int]) -> float | None:
    if value in {None, "", "-", "--"}:
        return None
    text = str(value).strip().replace(",", "")
    for unit, multiplier in units.items():
        if text.endswith(unit):
            return _optional_float(text[: -len(unit)]) * float(multiplier) if _optional_float(text[: -len(unit)]) is not None else None
    return _optional_float(text)


def _percent(value: object) -> float | None:
    return _optional_float(str(value).strip().removesuffix("%")) if value is not None else None


def _growth(current: float | None, prior: float | None) -> float | None:
    return (current / abs(prior) - 1) * 100 if current is not None and prior not in {None, 0} else None


def _required_float(value: object) -> float:
    parsed = _optional_float(value)
    if parsed is None:
        raise ValueError(f"Invalid numeric value: {value}")
    return parsed


def _optional_float(value: object) -> float | None:
    if value in {None, "", "-", "--"}:
        return None
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None
