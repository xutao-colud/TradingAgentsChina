from __future__ import annotations

import json
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Callable
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.market.realtime import RealtimeQuote
from app.config.runtime import load_runtime_settings
from app.rules.trading_rules import normalize_symbol


FetchText = Callable[[str], str]


@dataclass(frozen=True)
class StockMoneyFlowBreakdown:
    trade_date: str | None
    main_net_inflow: float | None
    super_large_net_inflow: float | None
    large_net_inflow: float | None
    medium_net_inflow: float | None
    small_net_inflow: float | None
    main_net_inflow_ratio: float | None
    visible_large_net_inflow: float | None
    hidden_follow_net_inflow: float | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class StockRealtimeSnapshot:
    symbol: str
    name: str | None
    price: float | None
    previous_close: float | None
    change_pct: float | None
    open: float | None
    high: float | None
    low: float | None
    volume: float | None
    amount: float | None
    turnover_rate: float | None
    market_cap: float | None
    float_market_cap: float | None
    industry: str | None
    market_board: str | None
    region: str | None
    concepts: list[str]
    money_flow: StockMoneyFlowBreakdown | None
    as_of: str
    source: str = "eastmoney_push2"
    data_status: str = "latest_available"
    error: str | None = None

    def to_quote(self) -> RealtimeQuote:
        return RealtimeQuote(
            symbol=self.symbol,
            name=self.name,
            price=self.price,
            previous_close=self.previous_close,
            change_pct=self.change_pct,
            volume=self.volume,
            amount=self.amount,
            trade_date=self.money_flow.trade_date if self.money_flow else None,
            trade_time=self.as_of,
            source=self.source,
            data_status=self.data_status,
            error=self.error,
        )

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["money_flow"] = self.money_flow.to_dict() if self.money_flow else None
        return payload


class EastmoneyStockSnapshotClient:
    """Best-effort stock snapshot with quote, sector tags, and order-size flows."""

    def __init__(self, fetch_text: FetchText | None = None, now: Callable[[], datetime] | None = None) -> None:
        self._fetch_text = fetch_text or _fetch_text
        self._now = now or datetime.now

    def fetch_snapshots(self, symbols: list[str]) -> dict[str, StockRealtimeSnapshot]:
        normalized = [normalize_symbol(symbol) for symbol in symbols]
        unique_symbols = list(dict.fromkeys(normalized))
        if not unique_symbols:
            return {}
        # A watchlist refresh needs two public requests per symbol. Bounded
        # concurrency keeps the local dashboard responsive without turning a
        # refresh into an unbounded burst against the public provider.
        workers = min(load_runtime_settings().get("runtime", "snapshot_max_workers"), len(unique_symbols))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="stock-snapshot") as executor:
            snapshots = list(executor.map(self.fetch_snapshot, unique_symbols))
        return dict(zip(unique_symbols, snapshots))

    def fetch_snapshot(self, symbol: str) -> StockRealtimeSnapshot:
        normalized = normalize_symbol(symbol)
        now = self._now()
        try:
            quote_payload = _load_json(self._fetch_text(_quote_url(normalized)))
            quote_data = quote_payload.get("data")
            if not isinstance(quote_data, dict):
                raise ValueError(f"No quote data returned for {normalized}")
            flow = self.fetch_money_flow(normalized)
            return _snapshot_from_data(normalized, quote_data, flow, now)
        except (OSError, URLError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            return _unavailable_snapshot(normalized, str(exc), now)

    def fetch_money_flow(self, symbol: str) -> StockMoneyFlowBreakdown | None:
        payload = _load_json(self._fetch_text(_flow_url(symbol)))
        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        klines = data.get("klines")
        if not isinstance(klines, list) or not klines:
            return None
        latest = str(klines[-1]).split(",")
        if len(latest) < 11:
            return None
        main = _num(latest[1])
        small = _num(latest[2])
        medium = _num(latest[3])
        large = _num(latest[4])
        super_large = _num(latest[5])
        return StockMoneyFlowBreakdown(
            trade_date=latest[0] or None,
            main_net_inflow=main,
            super_large_net_inflow=super_large,
            large_net_inflow=large,
            medium_net_inflow=medium,
            small_net_inflow=small,
            main_net_inflow_ratio=_num(latest[6]),
            visible_large_net_inflow=_sum_optional(super_large, large),
            hidden_follow_net_inflow=_sum_optional(medium, small),
        )


def _quote_url(symbol: str) -> str:
    params = {
        "secid": _secid(symbol),
        "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f116,f117,f127,f128,f129,f168,f170",
    }
    return load_runtime_settings().get("providers", "eastmoney", "stock_url") + "?" + urlencode(params, safe=",:+")


def _flow_url(symbol: str) -> str:
    params = {
        "secid": _secid(symbol),
        "klt": 101,
        "lmt": 1,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63",
    }
    return load_runtime_settings().get("providers", "eastmoney", "flow_url") + "?" + urlencode(params, safe=",:+")


def _secid(symbol: str) -> str:
    code, market = normalize_symbol(symbol).split(".", 1)
    if market == "SZ":
        return f"0.{code}"
    if market == "SH":
        return f"1.{code}"
    raise ValueError(f"Eastmoney snapshot does not support {market}: {symbol}")


def _snapshot_from_data(
    symbol: str,
    data: dict[str, object],
    flow: StockMoneyFlowBreakdown | None,
    now: datetime,
) -> StockRealtimeSnapshot:
    return StockRealtimeSnapshot(
        symbol=symbol,
        name=_normalize_name(_text(data.get("f58"))),
        price=_scaled(data.get("f43")),
        previous_close=_scaled(data.get("f60")),
        change_pct=_scaled(data.get("f170")),
        open=_scaled(data.get("f46")),
        high=_scaled(data.get("f44")),
        low=_scaled(data.get("f45")),
        volume=_num(data.get("f47")),
        amount=_num(data.get("f48")),
        turnover_rate=_scaled(data.get("f168")),
        market_cap=_num(data.get("f116")),
        float_market_cap=_num(data.get("f117")),
        industry=_text(data.get("f127")),
        market_board=_market_board(symbol),
        region=_text(data.get("f128")),
        concepts=_split_concepts(_text(data.get("f129"))),
        money_flow=flow,
        as_of=now.isoformat(timespec="seconds"),
        data_status=_data_status(now),
    )


def _unavailable_snapshot(symbol: str, error: str, now: datetime) -> StockRealtimeSnapshot:
    return StockRealtimeSnapshot(
        symbol=symbol,
        name=None,
        price=None,
        previous_close=None,
        change_pct=None,
        open=None,
        high=None,
        low=None,
        volume=None,
        amount=None,
        turnover_rate=None,
        market_cap=None,
        float_market_cap=None,
        industry=None,
        market_board=_market_board(symbol),
        region=None,
        concepts=[],
        money_flow=None,
        as_of=now.isoformat(timespec="seconds"),
        data_status="unavailable",
        error=error[:200],
    )


def _fetch_text(url: str) -> str:
    endpoints = load_runtime_settings().get("providers", "eastmoney")
    if not (url.startswith(endpoints["stock_url"]) or url.startswith(endpoints["flow_url"])):
        raise ValueError("Blocked stock snapshot URL")
    request = Request(url, headers=endpoints["headers"])
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


def _scaled(value: object) -> float | None:
    number = _num(value)
    return round(number / 100, 4) if number is not None else None


def _num(value: object) -> float | None:
    if value in (None, "-", "--", ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: object) -> str | None:
    if value in (None, "", "-", "--"):
        return None
    return str(value)


def _split_concepts(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _normalize_name(value: str | None) -> str | None:
    return value.replace("Ａ", "A") if value else None


def _market_board(symbol: str) -> str:
    code, market = normalize_symbol(symbol).split(".", 1)
    if market == "BJ":
        return "北交所"
    if market == "SH":
        if code.startswith("688"):
            return "科创板"
        if code.startswith("900"):
            return "沪市B股"
        return "沪市主板"
    if market == "SZ":
        if code.startswith(("300", "301")):
            return "创业板"
        if code.startswith("200"):
            return "深市B股"
        return "深市主板"
    return market


def _sum_optional(left: float | None, right: float | None) -> float | None:
    if left is None and right is None:
        return None
    return (left or 0.0) + (right or 0.0)


def _data_status(now: datetime) -> str:
    if now.isoweekday() > 5:
        return "latest_available"
    hhmm = now.hour * 100 + now.minute
    if 930 <= hhmm <= 1130 or 1300 <= hhmm <= 1500:
        return "real_time"
    return "latest_available"
