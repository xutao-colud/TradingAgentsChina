from __future__ import annotations

import re
import unicodedata

from app.schemas.report import DailyPrice, StockProfile
from app.config.runtime import load_runtime_settings


_SYMBOL_PATTERN = re.compile(r"^(?P<code>[0-9]{6})(?:\.?(?P<exchange>[A-Z]{2}))?$")
_IGNORABLE_SYMBOL_CHARS = re.compile(r"[\s\u200b\u200c\u200d\u2060\ufeff]+")


def normalize_symbol(raw_symbol: str) -> str:
    rules = load_runtime_settings().get("market_rules")
    symbol = _clean_symbol_input(raw_symbol)
    match = _SYMBOL_PATTERN.fullmatch(symbol)
    if match is None:
        raise ValueError(_symbol_format_error())
    code = match.group("code")
    suffix = match.group("exchange")

    inferred_exchange = _infer_exchange(code, rules)
    if inferred_exchange is None:
        raise ValueError(f"暂不支持股票代码 {code} 的市场前缀，请核对证券代码。")
    if suffix is not None:
        supported = set(rules["symbol_exchange_prefixes"]) | set(rules["convertible_bond_exchange_prefixes"])
        if suffix not in supported:
            raise ValueError(f"不支持交易所后缀 .{suffix}；允许值：{', '.join(sorted(supported))}。")
        if suffix != inferred_exchange:
            raise ValueError(f"股票代码 {code} 属于 {inferred_exchange}，不能标记为 {suffix}。")
    return f"{code}.{inferred_exchange}"


def _clean_symbol_input(raw_symbol: str) -> str:
    if not isinstance(raw_symbol, str):
        raise ValueError(_symbol_format_error())
    normalized = unicodedata.normalize("NFKC", raw_symbol)
    return _IGNORABLE_SYMBOL_CHARS.sub("", normalized).upper()


def _infer_exchange(code: str, rules: dict[str, object]) -> str | None:
    configured_prefixes = (
        rules["convertible_bond_exchange_prefixes"],
        rules["symbol_exchange_prefixes"],
    )
    for exchange_prefixes in configured_prefixes:
        if not isinstance(exchange_prefixes, dict):
            continue
        for exchange, prefixes in exchange_prefixes.items():
            if isinstance(prefixes, list) and code.startswith(tuple(str(prefix) for prefix in prefixes)):
                return str(exchange)
    return None


def _symbol_format_error() -> str:
    return "股票代码格式无效：请输入6位数字，可选交易所后缀，例如 600519、301526.SZ。"


def infer_board(symbol: str, profile_board: str | None = None) -> str:
    rules = load_runtime_settings().get("market_rules")
    code = symbol.split(".")[0]
    if profile_board:
        return profile_board
    for board, prefixes in rules["board_prefixes"].items():
        if code.startswith(tuple(prefixes)):
            return board
    if symbol.endswith(".BJ"):
        return "beijing"
    return "main"


def daily_limit_pct(profile: StockProfile) -> int:
    limits = load_runtime_settings().get("market_rules", "daily_limit_pct")
    if profile.is_st:
        return limits["st"]
    board = infer_board(profile.symbol, profile.board)
    return limits.get(board, limits["main"])


def invalid_conditions(profile: StockProfile, prices: list[DailyPrice]) -> list[str]:
    liquidity = load_runtime_settings().get("market_rules", "liquidity")
    conditions: list[str] = []
    if profile.is_suspended:
        conditions.append("股票处于停牌状态，不能形成参与结论。")
    if profile.is_st:
        conditions.append("股票带 ST/*ST 风险标识，需降低结论等级。")
    if prices:
        latest = prices[-1]
        if latest.amount is None:
            conditions.append("最近成交额数据缺失，流动性条件无法核验。")
        elif latest.amount < liquidity["minimum_amount"]:
            conditions.append("最近成交额低于 3000 万元，流动性不足。")
        if latest.turnover_rate is None:
            conditions.append("最近换手率数据缺失，短线流动性条件无法核验。")
        elif latest.turnover_rate < liquidity["minimum_turnover_rate"]:
            conditions.append("最近换手率偏低，短线资金承接弱。")
    else:
        conditions.append("缺少日线行情，无法完成技术与流动性判断。")
    return conditions
