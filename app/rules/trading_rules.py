from __future__ import annotations

from app.schemas.report import DailyPrice, StockProfile


def normalize_symbol(raw_symbol: str) -> str:
    symbol = raw_symbol.strip().upper()
    if "." in symbol:
        code, suffix = symbol.split(".", 1)
        return f"{code.zfill(6)}.{suffix}"
    code = symbol.zfill(6)
    if code.startswith(("600", "601", "603", "605", "688")):
        return f"{code}.SH"
    if code.startswith(("000", "001", "002", "003", "300", "301")):
        return f"{code}.SZ"
    if code.startswith(("430", "83", "87", "88", "92")):
        return f"{code}.BJ"
    return f"{code}.SH"


def infer_board(symbol: str, profile_board: str | None = None) -> str:
    code = symbol.split(".")[0]
    if profile_board:
        return profile_board
    if code.startswith("688"):
        return "star"
    if code.startswith(("300", "301")):
        return "chinext"
    if symbol.endswith(".BJ"):
        return "beijing"
    return "main"


def daily_limit_pct(profile: StockProfile) -> int:
    if profile.is_st:
        return 5
    board = infer_board(profile.symbol, profile.board)
    if board in {"star", "chinext"}:
        return 20
    if board == "beijing":
        return 30
    return 10


def invalid_conditions(profile: StockProfile, prices: list[DailyPrice]) -> list[str]:
    conditions: list[str] = []
    if profile.is_suspended:
        conditions.append("股票处于停牌状态，不能形成参与结论。")
    if profile.is_st:
        conditions.append("股票带 ST/*ST 风险标识，需降低结论等级。")
    if prices:
        latest = prices[-1]
        if latest.amount < 30_000_000:
            conditions.append("最近成交额低于 3000 万元，流动性不足。")
        if latest.turnover_rate < 0.2:
            conditions.append("最近换手率偏低，短线资金承接弱。")
    else:
        conditions.append("缺少日线行情，无法完成技术与流动性判断。")
    return conditions

