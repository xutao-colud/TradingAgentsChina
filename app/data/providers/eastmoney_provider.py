from __future__ import annotations

import json
import shutil
import subprocess
from datetime import date
from typing import Callable
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.data.providers.base import MarketDataProvider
from app.config.runtime import load_runtime_settings
from app.network.retry import retry_call
from app.market.stock_snapshot import EastmoneyStockSnapshotClient, StockRealtimeSnapshot
from app.rules.trading_rules import normalize_symbol
from app.schemas.report import (
    Announcement,
    DailyPrice,
    EvidenceSource,
    FundamentalSnapshot,
    MarketContext,
    MoneyFlowSnapshot,
    StockProfile,
)


FetchText = Callable[[str], str]


class EastmoneyRealtimeMarketDataProvider(MarketDataProvider):
    """Realtime-first provider for quote, daily bars, profile, and money flow.

    Unsupported dimensions delegate to an explicit real-source composition.
    Sample data is used only when a caller deliberately injects a sample provider.
    """

    def __init__(
        self,
        fallback: MarketDataProvider | None = None,
        snapshot_client: EastmoneyStockSnapshotClient | None = None,
        fetch_text: FetchText | None = None,
    ) -> None:
        if fallback is None:
            from app.data.providers.production_provider import ProductionMarketDataProvider

            fallback = ProductionMarketDataProvider()
        self.fallback = fallback
        self.snapshot_client = snapshot_client or EastmoneyStockSnapshotClient()
        self._fetch_text = fetch_text or _fetch_text
        self._snapshot_cache: dict[str, StockRealtimeSnapshot] = {}
        self._price_sources: dict[str, str] = {}
        self._price_as_of: dict[str, str] = {}
        self._flow_sources: dict[str, str] = {}
        self._flow_as_of: dict[str, str] = {}

    def get_stock_profile(self, symbol: str) -> StockProfile:
        normalized = normalize_symbol(symbol)
        fallback = self.fallback.get_stock_profile(normalized)
        snapshot = self._snapshot(normalized)
        if snapshot.data_status == "unavailable":
            return fallback
        name = snapshot.name or fallback.name
        return StockProfile(
            symbol=normalized,
            name=name,
            industry=snapshot.industry or fallback.industry,
            board=_schema_board(snapshot.market_board) or fallback.board,
            is_st=name.upper().startswith(("ST", "*ST")),
            is_suspended=fallback.is_suspended,
            concepts=snapshot.concepts,
            concept_source_id="profile-concept-001",
            list_date=fallback.list_date,
        )

    def get_daily_prices(self, symbol: str, analysis_date: str, lookback_days: int) -> list[DailyPrice]:
        normalized = normalize_symbol(symbol)
        try:
            prices = _prices_from_payload(_load_json(self._request_text(_kline_url(normalized, analysis_date, lookback_days))))
        except (OSError, URLError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            snapshot_prices = _prices_from_snapshot_for_date(self._snapshot(normalized), analysis_date)
            self._price_sources[normalized] = "eastmoney_snapshot" if snapshot_prices else "unavailable"
            if snapshot_prices:
                self._price_as_of[normalized] = snapshot_prices[-1].trade_date
            return snapshot_prices
        if not prices:
            snapshot_prices = _prices_from_snapshot_for_date(self._snapshot(normalized), analysis_date)
            self._price_sources[normalized] = "eastmoney_snapshot" if snapshot_prices else "unavailable"
            if snapshot_prices:
                self._price_as_of[normalized] = snapshot_prices[-1].trade_date
            return snapshot_prices
        self._price_sources[normalized] = "eastmoney_push2his"
        self._price_as_of[normalized] = prices[-1].trade_date
        return prices

    def get_fundamentals(self, symbol: str, analysis_date: str | None = None) -> FundamentalSnapshot:
        return self.fallback.get_fundamentals(symbol, analysis_date)

    def _request_text(self, url: str) -> str:
        return retry_call(lambda: self._fetch_text(url), operation_name="Eastmoney daily K-line")

    def get_money_flow(self, symbol: str, analysis_date: str) -> MoneyFlowSnapshot:
        normalized = normalize_symbol(symbol)
        snapshot = self._snapshot(normalized)
        try:
            flow = snapshot.money_flow or self.snapshot_client.fetch_money_flow(normalized)
        except (OSError, URLError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            flow = None
        if flow is None:
            fallback_flow = self.fallback.get_money_flow(normalized, analysis_date)
            self._flow_sources[normalized] = next(
                (
                    item.source_type
                    for item in self.fallback.get_evidence_sources(normalized, analysis_date)
                    if item.id == "flow-001"
                ),
                "unavailable",
            )
            return fallback_flow
        fallback_flow = self.fallback.get_money_flow(normalized, analysis_date)
        self._flow_sources[normalized] = "eastmoney_push2his"
        self._flow_as_of[normalized] = flow.trade_date or analysis_date
        return MoneyFlowSnapshot(
            main_net_inflow=flow.main_net_inflow,
            super_large_net_inflow=flow.super_large_net_inflow,
            margin_balance_change=fallback_flow.margin_balance_change,
            northbound_signal=fallback_flow.northbound_signal,
            turnover_rate=snapshot.turnover_rate if snapshot.turnover_rate is not None else fallback_flow.turnover_rate,
            block_trade_signal=fallback_flow.block_trade_signal,
            large_net_inflow=flow.large_net_inflow,
            medium_net_inflow=flow.medium_net_inflow,
            small_net_inflow=flow.small_net_inflow,
            as_of=flow.trade_date,
            northbound_net_inflow=fallback_flow.northbound_net_inflow,
        )

    def get_announcements(self, symbol: str, analysis_date: str) -> list[Announcement]:
        return self.fallback.get_announcements(symbol, analysis_date)

    def get_market_context(self, analysis_date: str) -> MarketContext:
        return self.fallback.get_market_context(analysis_date)

    def get_evidence_sources(self, symbol: str, analysis_date: str) -> list[EvidenceSource]:
        normalized = normalize_symbol(symbol)
        sources = [item for item in self.fallback.get_evidence_sources(normalized, analysis_date) if item.id not in {"price-001", "flow-001"}]
        price_source = self._price_sources.get(normalized, "eastmoney_push2his")
        flow_source = self._flow_sources.get(normalized, "eastmoney_push2his")
        sources.insert(0, EvidenceSource("flow-001", f"{normalized} 东方财富分档资金流", flow_source, self._flow_as_of.get(normalized, analysis_date)))
        sources.insert(0, EvidenceSource("price-001", f"{normalized} 东方财富日K线行情", price_source, self._price_as_of.get(normalized, analysis_date)))
        snapshot = self._snapshot_cache.get(normalized)
        if snapshot and snapshot.concepts:
            sources.append(EvidenceSource("profile-concept-001", f"{normalized} concept tags", snapshot.source, snapshot.as_of))
        return sources

    def _snapshot(self, symbol: str) -> StockRealtimeSnapshot:
        normalized = normalize_symbol(symbol)
        cached = self._snapshot_cache.get(normalized)
        if cached and cached.data_status != "unavailable":
            return cached
        snapshot = self.snapshot_client.fetch_snapshot(normalized)
        if snapshot.data_status != "unavailable":
            self._snapshot_cache[normalized] = snapshot
        return snapshot


def _kline_url(symbol: str, analysis_date: str, lookback_days: int) -> str:
    params = {
        "secid": _secid(symbol),
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": 101,
        "fqt": 1,
        "end": _end_date(analysis_date),
        "lmt": max(2, lookback_days),
    }
    return load_runtime_settings().get("providers", "eastmoney", "kline_url") + "?" + urlencode(params, safe=",:+")


def _prices_from_payload(payload: dict[str, object]) -> list[DailyPrice]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    klines = data.get("klines")
    if not isinstance(klines, list):
        return []
    prices: list[DailyPrice] = []
    for item in klines:
        fields = str(item).split(",")
        if len(fields) < 11:
            continue
        trade_date, open_price, close, high, low, volume, amount, _, _, _, turnover = fields[:11]
        prices.append(
            DailyPrice(
                trade_date=trade_date,
                open=_required_num(open_price),
                high=_required_num(high),
                low=_required_num(low),
                close=_required_num(close),
                volume=_required_num(volume),
                amount=_required_num(amount),
                turnover_rate=_required_num(turnover),
            )
        )
    return prices


def _prices_from_snapshot_for_date(snapshot: StockRealtimeSnapshot, analysis_date: str) -> list[DailyPrice]:
    """Use a quote snapshot only when it is explicitly dated for this request.

    A live quote has insufficient history for MA/volume calculations and must
    never be relabelled as a user-requested historical analysis date.
    """
    snapshot_date = snapshot.money_flow.trade_date if snapshot.money_flow else None
    required_values = (
        snapshot.price,
        snapshot.open,
        snapshot.high,
        snapshot.low,
        snapshot.volume,
        snapshot.amount,
    )
    if snapshot_date != analysis_date or any(value is None for value in required_values):
        return []
    trade_date = snapshot_date
    return [DailyPrice(
        trade_date=trade_date,
        open=float(snapshot.open),
        high=float(snapshot.high),
        low=float(snapshot.low),
        close=float(snapshot.price),
        volume=float(snapshot.volume),
        amount=float(snapshot.amount),
        turnover_rate=snapshot.turnover_rate,
    )]


def _secid(symbol: str) -> str:
    code, market = normalize_symbol(symbol).split(".", 1)
    if market == "SZ":
        return f"0.{code}"
    if market == "SH":
        return f"1.{code}"
    if market == "BJ":
        return f"0.{code}"
    raise ValueError(f"Unsupported market: {symbol}")


def _end_date(value: str) -> str:
    return value.replace("-", "") if value else date.today().strftime("%Y%m%d")


def _schema_board(value: str | None) -> str | None:
    mapping = {
        "沪市主板": "main",
        "深市主板": "main",
        "创业板": "chinext",
        "科创板": "star",
        "北交所": "beijing",
    }
    return mapping.get(value or "")


def _fetch_text(url: str) -> str:
    eastmoney = load_runtime_settings().get("providers", "eastmoney")
    if not url.startswith(eastmoney["kline_url"]):
        raise ValueError("Blocked Eastmoney K-line URL")
    request = Request(url, headers=eastmoney["headers"])
    try:
        with urlopen(request, timeout=load_runtime_settings().get("runtime", "network_timeout_seconds")) as response:
            body = response.read().decode("utf-8", errors="replace")
            if not body.strip():
                raise OSError("provider returned empty body")
            return body
    except (OSError, URLError):
        return _fetch_text_with_curl(url)


def _fetch_text_with_curl(url: str) -> str:
    curl = shutil.which("curl")
    if not curl:
        raise OSError("curl is unavailable and Python HTTP request failed")
    headers = load_runtime_settings().get("providers", "eastmoney", "headers")
    curl_headers = [argument for name, value in headers.items() for argument in ("-H", f"{name}: {value}")]
    completed = subprocess.run(
        [
            curl,
            "--http1.1",
            "-sS",
            *curl_headers,
            url,
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=load_runtime_settings().get("runtime", "network_timeout_seconds"),
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise OSError((completed.stderr or "curl returned no data").strip())
    return completed.stdout


def _load_json(raw: str) -> dict[str, object]:
    payload = json.loads(raw.strip())
    if not isinstance(payload, dict):
        raise ValueError("Provider payload is not an object")
    return payload


def _required_num(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid numeric field: {value}") from exc
