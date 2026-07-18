from __future__ import annotations

from app.schemas.report import DailyPrice, StockProfile
from app.config.runtime import load_runtime_settings


def normalize_symbol(raw_symbol: str) -> str:
    rules = load_runtime_settings().get("market_rules")
    symbol = raw_symbol.strip().upper()
    if "." in symbol:
        code, suffix = symbol.split(".", 1)
        return f"{code.zfill(6)}.{suffix}"
    code = symbol.zfill(6)
    for exchange, prefixes in rules["convertible_bond_exchange_prefixes"].items():
        if code.startswith(tuple(prefixes)):
            return f"{code}.{exchange}"
    for exchange, prefixes in rules["symbol_exchange_prefixes"].items():
        if code.startswith(tuple(prefixes)):
            return f"{code}.{exchange}"
    return f"{code}.{rules['default_exchange']}"


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
