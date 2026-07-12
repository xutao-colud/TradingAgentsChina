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
from app.data.providers.sample_provider import SampleMarketDataProvider
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


EASTMONEY_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
FetchText = Callable[[str], str]


class EastmoneyRealtimeMarketDataProvider(MarketDataProvider):
    """Realtime-first provider for quote, daily bars, profile, and money flow.

    Fundamentals, announcements, and broad market context still fall back to the
    deterministic provider until authenticated production sources are added.
    """

    def __init__(
        self,
        fallback: MarketDataProvider | None = None,
        snapshot_client: EastmoneyStockSnapshotClient | None = None,
        fetch_text: FetchText | None = None,
    ) -> None:
        self.fallback = fallback or SampleMarketDataProvider()
        self.snapshot_client = snapshot_client or EastmoneyStockSnapshotClient()
        self._fetch_text = fetch_text or _fetch_text
        self._snapshot_cache: dict[str, StockRealtimeSnapshot] = {}
        self._price_sources: dict[str, str] = {}
        self._flow_sources: dict[str, str] = {}

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
        )

    def get_daily_prices(self, symbol: str, analysis_date: str, lookback_days: int) -> list[DailyPrice]:
        normalized = normalize_symbol(symbol)
        try:
            prices = _prices_from_payload(_load_json(self._fetch_text(_kline_url(normalized, analysis_date, lookback_days))))
        except (OSError, URLError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            snapshot_prices = _prices_from_snapshot(self._snapshot(normalized), analysis_date)
            self._price_sources[normalized] = "eastmoney_snapshot" if snapshot_prices else "unavailable"
            return snapshot_prices
        if not prices:
            snapshot_prices = _prices_from_snapshot(self._snapshot(normalized), analysis_date)
            self._price_sources[normalized] = "eastmoney_snapshot" if snapshot_prices else "unavailable"
            return snapshot_prices
        self._price_sources[normalized] = "eastmoney_push2his"
        return prices

    def get_fundamentals(self, symbol: str) -> FundamentalSnapshot:
        return self.fallback.get_fundamentals(symbol)

    def get_money_flow(self, symbol: str, analysis_date: str) -> MoneyFlowSnapshot:
        normalized = normalize_symbol(symbol)
        snapshot = self._snapshot(normalized)
        try:
            flow = snapshot.money_flow or self.snapshot_client.fetch_money_flow(normalized)
        except (OSError, URLError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            flow = None
        if flow is None:
            self._flow_sources[normalized] = "offline_sample"
            return self.fallback.get_money_flow(normalized, analysis_date)
        self._flow_sources[normalized] = "eastmoney_push2his"
        return MoneyFlowSnapshot(
            main_net_inflow=flow.main_net_inflow or 0.0,
            super_large_net_inflow=flow.super_large_net_inflow or 0.0,
            margin_balance_change=self.fallback.get_money_flow(normalized, analysis_date).margin_balance_change,
            northbound_signal="北向暂未接入；使用东方财富分档资金",
            turnover_rate=snapshot.turnover_rate or 0.0,
            block_trade_signal="大宗交易暂未接入实时源",
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
        sources.insert(0, EvidenceSource("flow-001", f"{normalized} 东方财富分档资金流", flow_source, analysis_date))
        sources.insert(0, EvidenceSource("price-001", f"{normalized} 东方财富日K线行情", price_source, analysis_date))
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
    return EASTMONEY_KLINE_URL + "?" + urlencode(params, safe=",:+")


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


def _prices_from_snapshot(snapshot: StockRealtimeSnapshot, analysis_date: str) -> list[DailyPrice]:
    if snapshot.price is None:
        return []
    trade_date = snapshot.money_flow.trade_date if snapshot.money_flow and snapshot.money_flow.trade_date else analysis_date
    latest = DailyPrice(
        trade_date=trade_date,
        open=snapshot.open if snapshot.open is not None else snapshot.price,
        high=snapshot.high if snapshot.high is not None else snapshot.price,
        low=snapshot.low if snapshot.low is not None else snapshot.price,
        close=snapshot.price,
        volume=snapshot.volume or 0.0,
        amount=snapshot.amount or 0.0,
        turnover_rate=snapshot.turnover_rate or 0.0,
    )
    if snapshot.previous_close is None:
        return [latest]
    previous = DailyPrice(
        trade_date=trade_date,
        open=snapshot.previous_close,
        high=snapshot.previous_close,
        low=snapshot.previous_close,
        close=snapshot.previous_close,
        volume=0.0,
        amount=0.0,
        turnover_rate=0.0,
    )
    return [previous, latest]


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
    if not url.startswith(EASTMONEY_KLINE_URL):
        raise ValueError("Blocked Eastmoney K-line URL")
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) TradingAgentsChina/0.1",
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://quote.eastmoney.com/",
        },
    )
    try:
        with urlopen(request, timeout=8) as response:
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
    completed = subprocess.run(
        [
            curl,
            "--http1.1",
            "-sS",
            "-H",
            "User-Agent: TradingAgentsChina/0.1",
            "-H",
            "Referer: https://quote.eastmoney.com/",
            url,
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=8,
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
