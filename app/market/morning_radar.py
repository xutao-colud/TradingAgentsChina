from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Callable
from urllib.error import URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from app.rules.trading_rules import normalize_symbol
from app.config.runtime import load_runtime_settings
from app.network.retry import retry_call
from app.market.realtime import RealtimeQuote


FetchText = Callable[[str], str]
QuoteFetcher = Callable[[list[str]], dict[str, RealtimeQuote]]
SecondaryRadarFetcher = Callable[[int, datetime], "MorningRadarSnapshot | None"]


@dataclass(frozen=True)
class SectorFlow:
    code: str
    name: str
    change_pct: float | None
    main_net_inflow: float | None
    main_net_inflow_ratio: float | None
    super_large_net_inflow: float | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class FastMover:
    symbol: str
    name: str
    price: float | None
    change_pct: float | None
    speed_pct: float | None
    amount: float | None
    main_net_inflow: float | None
    main_net_inflow_ratio: float | None
    trigger_reason: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class MorningRadarSnapshot:
    as_of: str
    source: str
    data_status: str
    market_phase: str
    top_inflow_sectors: list[SectorFlow]
    top_outflow_sectors: list[SectorFlow]
    fast_movers: list[FastMover]
    shortline_read: str
    risks: list[str]
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["top_inflow_sectors"] = [item.to_dict() for item in self.top_inflow_sectors]
        payload["top_outflow_sectors"] = [item.to_dict() for item in self.top_outflow_sectors]
        payload["fast_movers"] = [item.to_dict() for item in self.fast_movers]
        return payload


class MorningMoneyRadarClient:
    """Best-effort read-only intraday radar for short-line research.

    The public endpoint can be unavailable or change fields. The caller must
    inspect `data_status` and `source` before treating the result as live.
    """

    def __init__(
        self,
        fetch_text: FetchText | None = None,
        now: Callable[[], datetime] | None = None,
        quote_fetcher: QuoteFetcher | None = None,
        secondary_fetcher: SecondaryRadarFetcher | None = None,
    ) -> None:
        self._fetch_text = fetch_text or _fetch_text
        self._now = now or datetime.now
        self._quote_fetcher = quote_fetcher
        self._secondary_fetcher = secondary_fetcher

    def fetch_snapshot(self, limit: int | None = None, fallback_symbols: list[str] | None = None) -> MorningRadarSnapshot:
        settings = load_runtime_settings().get("morning_radar")
        requested_limit = settings["default_limit"] if limit is None else int(limit)
        safe_limit = max(settings["minimum_limit"], min(settings["maximum_limit"], requested_limit))
        try:
            inflow, inflow_source = self._fetch_sector_flows(sort_desc=True, limit=safe_limit)
            outflow, outflow_source = self._fetch_sector_flows(sort_desc=False, limit=safe_limit)
            movers, mover_source = self._fetch_fast_movers(limit=safe_limit)
            if not inflow and not outflow and not movers:
                raise ValueError("No radar rows returned by provider")
            now = self._now()
            phase = _market_phase(now)
            status = _data_status(now, phase)
            risks = [
                "盘中资金流变化很快，只能作为短线观察雷达，不构成买入指令。",
                "板块净流入需要结合龙头强度、炸板率、成交额和个股位置复核。",
            ]
            if status != "real_time":
                risks.insert(0, "当前不在交易日连续竞价时段，雷达可能反映最近可用交易数据。")
            return MorningRadarSnapshot(
                as_of=now.isoformat(timespec="seconds"),
                source=_combined_source(inflow_source, outflow_source, mover_source),
                data_status=status,
                market_phase=phase,
                top_inflow_sectors=inflow,
                top_outflow_sectors=outflow,
                fast_movers=movers,
                shortline_read=_shortline_read(inflow, outflow, movers),
                risks=risks,
            )
        except (OSError, URLError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            secondary = self._secondary_fallback(safe_limit)
            if secondary is not None:
                return replace(
                    secondary,
                    error="东方财富盘中全市场列表暂不可用，已切换至经校验的盘后行业资金备选源。",
                )
            fallback = self._tracked_universe_fallback(
                fallback_symbols or [],
                safe_limit,
            )
            if fallback is not None:
                return fallback
            return unavailable_morning_radar(error=str(exc), as_of=self._now().isoformat(timespec="seconds"))

    def _secondary_fallback(self, limit: int) -> MorningRadarSnapshot | None:
        if self._secondary_fetcher is None:
            return None
        try:
            return self._secondary_fetcher(limit, self._now())
        except (OSError, URLError, ValueError, KeyError, TypeError):
            return None

    def _tracked_universe_fallback(
        self,
        symbols: list[str],
        limit: int,
    ) -> MorningRadarSnapshot | None:
        """Return a clearly scoped quote-only fallback; never call it market-wide."""
        if self._quote_fetcher is None:
            return None
        settings = load_runtime_settings().get("morning_radar")
        tracked = list(dict.fromkeys(symbols))[: settings["fallback_maximum_symbols"]]
        if not tracked:
            return None
        quotes = self._quote_fetcher(tracked)
        available = [
            quote
            for quote in quotes.values()
            if quote.data_status != "unavailable" and quote.price is not None and quote.change_pct is not None
        ]
        if not available:
            return None
        movers = [
            FastMover(
                symbol=quote.symbol,
                name=quote.name or quote.symbol,
                price=quote.price,
                change_pct=quote.change_pct,
                speed_pct=None,
                amount=quote.amount,
                main_net_inflow=None,
                main_net_inflow_ratio=None,
                trigger_reason="跟踪池涨跌幅排序；该降级源不含板块资金流和主力资金字段。",
            )
            for quote in sorted(
                available,
                key=lambda item: (item.change_pct or 0, item.amount or 0),
                reverse=True,
            )[:limit]
        ]
        now = self._now()
        return MorningRadarSnapshot(
            as_of=_latest_quote_as_of(available, now),
            source="sina_tracked_universe",
            data_status="tracked_universe",
            market_phase=_market_phase(now),
            top_inflow_sectors=[],
            top_outflow_sectors=[],
            fast_movers=movers,
            shortline_read=(
                "东方财富全市场盘中雷达暂不可用。当前仅展示已核验的自选、持仓和机会池报价快照；"
                "不得据此推断全市场板块资金流。"
            ),
            risks=[
                "降级源只覆盖跟踪池，不代表全市场。",
                "该源不提供板块资金流、主力净流入和涨速；相关字段已明确留空。",
                "降级雷达不生成交易指令。",
            ],
            error="东方财富全市场列表接口暂不可用，已启用跟踪池报价快照降级。",
        )

    def _fetch_sector_flows(self, sort_desc: bool, limit: int) -> tuple[list[SectorFlow], str]:
        raw, source = self._request_text(
            _eastmoney_url(
                {
                    "pn": 1,
                    "pz": limit,
                    "po": 1 if sort_desc else 0,
                    "np": 1,
                    "fltt": 2,
                    "invt": 2,
                    "fid": "f62",
                    "fs": "m:90+t:2",
                    "fields": "f12,f14,f3,f62,f66,f184",
                }
            )
        )
        payload = _load_json(
            raw
        )
        return [_sector_from_row(row) for row in _diff_rows(payload)], source

    def _fetch_fast_movers(self, limit: int) -> tuple[list[FastMover], str]:
        raw, source = self._request_text(
            _eastmoney_url(
                {
                    "pn": 1,
                    "pz": limit,
                    "po": 1,
                    "np": 1,
                    "fltt": 2,
                    "invt": 2,
                    "fid": "f22",
                    "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
                    "fields": "f12,f14,f2,f3,f6,f22,f62,f184",
                }
            )
        )
        payload = _load_json(
            raw
        )
        return [_mover_from_row(row) for row in _diff_rows(payload)], source

    def _request_text(self, url: str) -> tuple[str, str]:
        settings = load_runtime_settings().get("providers", "eastmoney")
        query = urlsplit(url).query
        errors: list[Exception] = []
        for base_url in [settings["clist_url"], *settings["clist_fallback_urls"]]:
            candidate = base_url + (f"?{query}" if query else "")
            try:
                raw = retry_call(lambda: self._fetch_text(candidate), operation_name="Eastmoney morning radar")
                return raw, _eastmoney_source(candidate)
            except (OSError, URLError) as exc:
                errors.append(exc)
        raise OSError(f"All configured Eastmoney radar endpoints failed: {errors[-1] if errors else 'no endpoint'}")


def unavailable_morning_radar(error: str | None = None, as_of: str | None = None) -> MorningRadarSnapshot:
    return MorningRadarSnapshot(
        as_of=as_of or datetime.now().isoformat(timespec="seconds"),
        source="eastmoney_push2",
        data_status="unavailable",
        market_phase="实时源不可用",
        top_inflow_sectors=[],
        top_outflow_sectors=[],
        fast_movers=[],
        shortline_read="盘中资金雷达未拿到可核验的实时数据，本次不展示样例板块或样例个股；请稍后刷新或切换数据源。",
        risks=[
            "实时资金源不可用时不生成短线方向判断，避免把旧数据或样例数据当成盘面信号。",
            "短线策略需要确认交易时段、成交额、涨速、主力净流入和龙头反馈后再进入研究流程。",
        ],
        error=error[:200] if error else None,
    )


def sample_morning_radar(error: str | None = None, as_of: str | None = None) -> MorningRadarSnapshot:
    return MorningRadarSnapshot(
        as_of=as_of or datetime.now().isoformat(timespec="seconds"),
        source="offline_sample",
        data_status="sample",
        market_phase="非实时样例",
        top_inflow_sectors=[
            SectorFlow("BK1030", "半导体", 2.36, 1_860_000_000, 6.8, 620_000_000),
            SectorFlow("BK1124", "机器人", 1.92, 1_240_000_000, 5.1, 410_000_000),
            SectorFlow("BK0737", "消费电子", 1.18, 890_000_000, 3.7, 220_000_000),
        ],
        top_outflow_sectors=[
            SectorFlow("BK0475", "银行", -0.72, -1_350_000_000, -4.3, -320_000_000),
            SectorFlow("BK0474", "白酒", -1.06, -980_000_000, -3.8, -210_000_000),
            SectorFlow("BK0429", "煤炭", -0.88, -760_000_000, -3.2, -180_000_000),
        ],
        fast_movers=[
            FastMover("688981.SH", "中芯国际", 78.5, 5.2, 1.6, 5_800_000_000, 420_000_000, 7.2, "涨速靠前且主力净流入为正"),
            FastMover("000725.SZ", "京东方A", 4.68, 3.1, 1.2, 3_400_000_000, 260_000_000, 4.8, "显示面板方向异动，成交额放大"),
            FastMover("300750.SZ", "宁德时代", 198.2, 2.4, 0.9, 6_200_000_000, 180_000_000, 2.9, "权重股拉升，需观察持续性"),
        ],
        shortline_read="样例雷达显示资金偏向科技成长，银行/白酒偏流出；短线只适合作为观察清单，等待龙头和成交额确认。",
        risks=[
            "当前为离线样例，不代表真实盘面。",
            "早盘急拉容易冲高回落，短线战法需结合情绪周期和个人止损规则。",
        ],
        error=error[:200] if error else None,
    )


def _eastmoney_url(params: dict[str, object]) -> str:
    return load_runtime_settings().get("providers", "eastmoney", "clist_url") + "?" + urlencode(params, safe=",:+")


def _fetch_text(url: str) -> str:
    eastmoney = load_runtime_settings().get("providers", "eastmoney")
    allowed = [eastmoney["clist_url"], *eastmoney["clist_fallback_urls"]]
    if not any(url.startswith(item) for item in allowed):
        raise ValueError("Blocked morning radar URL")
    request = Request(url, headers=eastmoney["headers"])
    try:
        with urlopen(request, timeout=load_runtime_settings().get("runtime", "network_timeout_seconds")) as response:
            return response.read().decode("utf-8", errors="replace")
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


def _eastmoney_source(url: str) -> str:
    host = (urlsplit(url).hostname or "unknown").split(".", 1)[0]
    return f"eastmoney_{host}"


def _combined_source(*sources: str) -> str:
    return "+".join(dict.fromkeys(sources))


def _load_json(raw: str) -> dict[str, object]:
    stripped = raw.strip()
    if stripped.startswith(("jQuery", "callback")):
        start = stripped.find("(")
        end = stripped.rfind(")")
        if start >= 0 and end > start:
            stripped = stripped[start + 1 : end]
    payload = json.loads(stripped)
    if not isinstance(payload, dict):
        raise ValueError("Provider payload is not an object")
    return payload


def _diff_rows(payload: dict[str, object]) -> list[dict[str, object]]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    diff = data.get("diff")
    if not isinstance(diff, list):
        return []
    return [row for row in diff if isinstance(row, dict)]


def _sector_from_row(row: dict[str, object]) -> SectorFlow:
    return SectorFlow(
        code=str(row.get("f12") or ""),
        name=str(row.get("f14") or "未知板块"),
        change_pct=_num(row.get("f3")),
        main_net_inflow=_num(row.get("f62")),
        main_net_inflow_ratio=_num(row.get("f184")),
        super_large_net_inflow=_num(row.get("f66")),
    )


def _mover_from_row(row: dict[str, object]) -> FastMover:
    symbol = _normalize_stock_symbol(str(row.get("f12") or ""))
    speed = _num(row.get("f22"))
    main = _num(row.get("f62"))
    ratio = _num(row.get("f184"))
    return FastMover(
        symbol=symbol,
        name=str(row.get("f14") or "未知股票"),
        price=_num(row.get("f2")),
        change_pct=_num(row.get("f3")),
        speed_pct=speed,
        amount=_num(row.get("f6")),
        main_net_inflow=main,
        main_net_inflow_ratio=ratio,
        trigger_reason=_trigger_reason(speed, main, ratio),
    )


def _normalize_stock_symbol(code: str) -> str:
    if not code.isdigit() or len(code) != 6:
        return code
    return normalize_symbol(code)


def _num(value: object) -> float | None:
    if value in (None, "-", "--", ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _latest_quote_as_of(quotes: list[RealtimeQuote], fallback: datetime) -> str:
    timestamps: list[datetime] = []
    for quote in quotes:
        if not quote.trade_date or not quote.trade_time:
            continue
        try:
            timestamps.append(datetime.fromisoformat(f"{quote.trade_date}T{quote.trade_time}"))
        except ValueError:
            continue
    return (max(timestamps) if timestamps else fallback).isoformat(timespec="seconds")


def _market_phase(now: datetime) -> str:
    if now.isoweekday() > 5:
        return "非交易日"
    hhmm = now.hour * 100 + now.minute
    if 925 <= hhmm < 930:
        return "集合竞价后"
    if 930 <= hhmm <= 1030:
        return "早盘主升观察"
    if 1030 < hhmm <= 1130:
        return "早盘分歧确认"
    if 1300 <= hhmm <= 1500:
        return "午后延续观察"
    return "非连续竞价时段"


def _data_status(now: datetime, phase: str) -> str:
    if now.isoweekday() <= 5 and phase in {"早盘主升观察", "早盘分歧确认", "午后延续观察"}:
        return "real_time"
    return "latest_available"


def _trigger_reason(speed: float | None, main: float | None, ratio: float | None) -> str:
    parts: list[str] = []
    if speed is not None and speed > 0:
        parts.append(f"涨速 {speed:.2f}%")
    if main is not None and main > 0:
        parts.append("主力净流入")
    if ratio is not None and ratio > 0:
        parts.append(f"主力净占比 {ratio:.2f}%")
    return "，".join(parts) if parts else "价格异动，需复核资金与成交额"


def _shortline_read(inflow: list[SectorFlow], outflow: list[SectorFlow], movers: list[FastMover]) -> str:
    if not inflow and not movers:
        return "暂无清晰盘中主线，短线策略以观察和风控为主。"
    lead = inflow[0].name if inflow else "未知板块"
    mover = movers[0].name if movers else "暂无急拉个股"
    weak = outflow[0].name if outflow else "暂无明显流出板块"
    return f"盘中资金最强方向暂看 {lead}，急拉观察股为 {mover}，流出压力较大的方向是 {weak}；短线只在板块持续放量且龙头不炸板时考虑。"
