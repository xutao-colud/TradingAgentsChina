from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

from app.rules.trading_rules import normalize_symbol
from app.config.runtime import load_runtime_settings
from app.network.curl_transport import fetch_text_with_curl
from app.network.retry import retry_call


_LINE_PATTERN = re.compile(r'var hq_str_([a-z]{2}\d{6})="([^"]*)";')
_TENCENT_LINE_PATTERN = re.compile(r'v_((?:sh|sz|bj)\d{6})="([^"]*)";')
_IDENTIFIER_PATTERN = re.compile(r"^(sh|sz)\d{6}$")
FetchText = Callable[[str], str]


@dataclass(frozen=True)
class RealtimeQuote:
    symbol: str
    name: str | None
    price: float | None
    previous_close: float | None
    change_pct: float | None
    volume: float | None
    amount: float | None
    trade_date: str | None
    trade_time: str | None
    source: str = "sina"
    data_status: str = "real_time"
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def is_continuous_trading_session(now: datetime) -> bool:
    if now.isoweekday() > 5:
        return False
    hhmm = now.hour * 100 + now.minute
    return 930 <= hhmm <= 1130 or 1300 <= hhmm <= 1500


def quote_is_usable(
    quote: RealtimeQuote,
    now: datetime | None = None,
    *,
    allow_previous_session: bool = True,
) -> bool:
    """Admit only priced, dated quotes inside the configured replay window."""
    current = now or datetime.now()
    if quote.data_status == "unavailable" or quote.price is None or quote.price <= 0:
        return False
    if not quote.trade_date:
        return False
    try:
        trade_day = datetime.fromisoformat(quote.trade_date).date()
    except ValueError:
        return False
    age_days = (current.date() - trade_day).days
    if age_days < 0:
        return False
    if age_days == 0:
        return True
    source_lag = load_runtime_settings().get("providers", "high_availability", "source_lag")
    maximum = int(source_lag["maximum_calendar_days"]["realtime-quote"])
    return (
        allow_previous_session
        and bool(source_lag["previous_session_market_replay_enabled"])
        and age_days <= maximum
    )


def quote_priority(quote: RealtimeQuote, now: datetime | None = None) -> tuple[int, str, str]:
    """Rank valid candidates without letting a prior close mask a live quote."""
    current = now or datetime.now()
    if not quote_is_usable(quote, current):
        return (0, "", "")
    same_day = quote.trade_date == current.date().isoformat()
    status_rank = 3 if quote.data_status == "real_time" else 2 if same_day else 1
    return (status_rank, quote.trade_date or "", quote.trade_time or "")


class SinaRealtimeQuoteClient:
    """Read-only adapter for a fixed public quote endpoint.

    The provider response is treated as untrusted data. Only exact quote lines
    and numeric fields are accepted; no external text is evaluated or sent to
    the model layer.
    """

    def __init__(self, fetch_text: FetchText | None = None, now: Callable[[], datetime] | None = None) -> None:
        self._fetch_text = fetch_text or _fetch_text
        self._now = now or datetime.now

    def fetch_quotes(self, symbols: list[str]) -> dict[str, RealtimeQuote]:
        normalized = [normalize_symbol(symbol) for symbol in symbols]
        identifiers = {symbol: _to_sina_identifier(symbol) for symbol in normalized}
        if not identifiers:
            return {}
        url = load_runtime_settings().get("providers", "sina", "quote_url") + ",".join(identifiers.values())
        try:
            raw = retry_call(lambda: self._fetch_text(url), operation_name="Sina real-time quote")
            parsed = _parse_response(raw, identifiers, self._now())
        except (URLError, OSError, ValueError) as exc:
            return {symbol: _unavailable_quote(symbol, str(exc)) for symbol in normalized}

        return {
            symbol: parsed.get(symbol, _unavailable_quote(symbol, "Quote was not returned by provider"))
            for symbol in normalized
        }


class TencentRealtimeQuoteClient:
    """Batch quote fallback backed by Tencent's public quote response."""

    def __init__(self, fetch_text: FetchText | None = None, now: Callable[[], datetime] | None = None) -> None:
        self._fetch_text = fetch_text or _fetch_tencent_text
        self._now = now or datetime.now

    def fetch_quotes(self, symbols: list[str]) -> dict[str, RealtimeQuote]:
        normalized = [normalize_symbol(symbol) for symbol in symbols]
        identifiers = {symbol: _to_tencent_identifier(symbol) for symbol in normalized}
        if not identifiers:
            return {}
        url = load_runtime_settings().get("providers", "tencent", "quote_url") + ",".join(identifiers.values())
        try:
            raw = retry_call(lambda: self._fetch_text(url), operation_name="Tencent real-time quote")
            parsed = _parse_tencent_response(raw, identifiers, self._now())
        except (URLError, OSError, ValueError) as exc:
            return {symbol: _unavailable_quote(symbol, str(exc), source="tencent") for symbol in normalized}
        return {
            symbol: parsed.get(symbol, _unavailable_quote(symbol, "Quote was not returned by provider", source="tencent"))
            for symbol in normalized
        }


def _to_sina_identifier(symbol: str) -> str:
    code, market = symbol.split(".", 1)
    if not code.isdigit() or len(code) != 6:
        raise ValueError(f"Invalid A-share symbol: {symbol}")
    if market == "SH":
        identifier = f"sh{code}"
    elif market == "SZ":
        identifier = f"sz{code}"
    else:
        raise ValueError(f"Real-time quote provider does not support {market}: {symbol}")
    if not _IDENTIFIER_PATTERN.fullmatch(identifier):
        raise ValueError("Invalid quote identifier")
    return identifier


def _to_tencent_identifier(symbol: str) -> str:
    code, market = symbol.split(".", 1)
    prefix = {"SH": "sh", "SZ": "sz", "BJ": "bj"}.get(market)
    if prefix is None or not code.isdigit() or len(code) != 6:
        raise ValueError(f"Tencent real-time quote provider does not support {symbol}")
    return prefix + code


def _parse_response(raw: str, identifiers: dict[str, str], now: datetime) -> dict[str, RealtimeQuote]:
    by_identifier = {identifier: symbol for symbol, identifier in identifiers.items()}
    quotes: dict[str, RealtimeQuote] = {}
    for identifier, payload in _LINE_PATTERN.findall(raw):
        symbol = by_identifier.get(identifier)
        if symbol is None or not payload:
            continue
        fields = payload.split(",")
        if len(fields) < 32:
            continue
        previous_close = _as_float(fields[2])
        price = _as_float(fields[3])
        change_pct = None
        if price is not None and previous_close not in (None, 0):
            change_pct = round((price / previous_close - 1) * 100, 2)
        trade_date = fields[30] or None
        quotes[symbol] = RealtimeQuote(
            symbol=symbol,
            name=fields[0] or None,
            price=price,
            previous_close=previous_close,
            change_pct=change_pct,
            volume=_as_float(fields[8]),
            amount=_as_float(fields[9]),
            trade_date=trade_date,
            trade_time=fields[31] or None,
            data_status=_data_status(now, trade_date),
        )
    return quotes


def _parse_tencent_response(raw: str, identifiers: dict[str, str], now: datetime) -> dict[str, RealtimeQuote]:
    by_identifier = {identifier: symbol for symbol, identifier in identifiers.items()}
    quotes: dict[str, RealtimeQuote] = {}
    for identifier, payload in _TENCENT_LINE_PATTERN.findall(raw):
        symbol = by_identifier.get(identifier)
        if symbol is None:
            continue
        fields = payload.split("~")
        if len(fields) < 38:
            continue
        timestamp = fields[30].strip()
        trade_date = f"{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]}" if len(timestamp) >= 8 and timestamp[:8].isdigit() else None
        trade_time = f"{timestamp[8:10]}:{timestamp[10:12]}:{timestamp[12:14]}" if len(timestamp) >= 14 and timestamp[8:14].isdigit() else None
        price = _as_float(fields[3])
        previous_close = _as_float(fields[4])
        change_pct = _as_float(fields[32])
        volume, amount = _tencent_volume_amount(fields)
        quotes[symbol] = RealtimeQuote(
            symbol=symbol,
            name=fields[1].strip() or None,
            price=price,
            previous_close=previous_close,
            change_pct=change_pct,
            volume=volume,
            amount=amount,
            trade_date=trade_date,
            trade_time=trade_time,
            source="tencent",
            data_status=_data_status(now, trade_date),
        )
    return quotes


def _tencent_volume_amount(fields: list[str]) -> tuple[float | None, float | None]:
    if len(fields) > 35:
        parts = fields[35].split("/")
        if len(parts) >= 3:
            lots = _as_float(parts[1])
            amount = _as_float(parts[2])
            return lots, amount
    lots = _as_float(fields[6]) if len(fields) > 6 else None
    amount_ten_thousand = _as_float(fields[37]) if len(fields) > 37 else None
    return (
        lots,
        amount_ten_thousand * 10000 if amount_ten_thousand is not None else None,
    )


def _as_float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def _unavailable_quote(symbol: str, error: str, source: str = "sina") -> RealtimeQuote:
    return RealtimeQuote(
        symbol=symbol,
        name=None,
        price=None,
        previous_close=None,
        change_pct=None,
        volume=None,
        amount=None,
        trade_date=None,
        trade_time=None,
        data_status="unavailable",
        source=source,
        error=error[:200],
    )


def _data_status(now: datetime, trade_date: str | None) -> str:
    if trade_date != now.date().isoformat() or now.isoweekday() > 5:
        return "latest_available"
    hhmm = now.hour * 100 + now.minute
    if 930 <= hhmm <= 1130 or 1300 <= hhmm <= 1500:
        return "real_time"
    return "latest_available"


def _fetch_text(url: str) -> str:
    sina = load_runtime_settings().get("providers", "sina")
    if not url.startswith(sina["quote_url"]):
        raise ValueError("Blocked quote URL")
    request = Request(url, headers=sina["headers"])
    with urlopen(request, timeout=load_runtime_settings().get("runtime", "network_timeout_seconds")) as response:
        return response.read().decode("gbk", errors="replace")


def _fetch_tencent_text(url: str) -> str:
    config = load_runtime_settings().get("providers", "tencent")
    if not url.startswith(config["quote_url"]):
        raise ValueError("Blocked Tencent quote URL")
    if config["curl_first"]:
        try:
            return fetch_text_with_curl(url, config["headers"], encoding="gbk")
        except OSError:
            pass
    request = Request(url, headers=config["headers"])
    with urlopen(request, timeout=load_runtime_settings().get("runtime", "network_timeout_seconds")) as response:
        return response.read().decode("gbk", errors="replace")
