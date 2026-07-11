from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

from app.rules.trading_rules import normalize_symbol


SINA_QUOTE_URL = "https://hq.sinajs.cn/list="
_LINE_PATTERN = re.compile(r'var hq_str_([a-z]{2}\d{6})="([^"]*)";')
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


class SinaRealtimeQuoteClient:
    """Read-only adapter for a fixed public quote endpoint.

    The provider response is treated as untrusted data. Only exact quote lines
    and numeric fields are accepted; no external text is evaluated or sent to
    the model layer.
    """

    def __init__(self, fetch_text: FetchText | None = None) -> None:
        self._fetch_text = fetch_text or _fetch_text

    def fetch_quotes(self, symbols: list[str]) -> dict[str, RealtimeQuote]:
        normalized = [normalize_symbol(symbol) for symbol in symbols]
        identifiers = {symbol: _to_sina_identifier(symbol) for symbol in normalized}
        if not identifiers:
            return {}
        url = SINA_QUOTE_URL + ",".join(identifiers.values())
        try:
            raw = self._fetch_text(url)
            parsed = _parse_response(raw, identifiers)
        except (URLError, OSError, ValueError) as exc:
            return {symbol: _unavailable_quote(symbol, str(exc)) for symbol in normalized}

        return {
            symbol: parsed.get(symbol, _unavailable_quote(symbol, "Quote was not returned by provider"))
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


def _parse_response(raw: str, identifiers: dict[str, str]) -> dict[str, RealtimeQuote]:
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
        quotes[symbol] = RealtimeQuote(
            symbol=symbol,
            name=fields[0] or None,
            price=price,
            previous_close=previous_close,
            change_pct=change_pct,
            volume=_as_float(fields[8]),
            amount=_as_float(fields[9]),
            trade_date=fields[30] or None,
            trade_time=fields[31] or None,
        )
    return quotes


def _as_float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def _unavailable_quote(symbol: str, error: str) -> RealtimeQuote:
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
        error=error[:200],
    )


def _fetch_text(url: str) -> str:
    if not url.startswith(SINA_QUOTE_URL):
        raise ValueError("Blocked quote URL")
    request = Request(url, headers={"User-Agent": "TradingAgentsChina/0.1", "Referer": "https://finance.sina.com.cn"})
    with urlopen(request, timeout=8) as response:
        return response.read().decode("gbk", errors="replace")
