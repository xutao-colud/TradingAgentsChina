from __future__ import annotations

from typing import Any

from app.market.realtime import RealtimeQuote


def build_portfolio_snapshot(portfolio: dict[str, Any], quotes: dict[str, RealtimeQuote]) -> dict[str, Any]:
    cash = float(portfolio.get("cash_balance", 0.0))
    rows: list[dict[str, Any]] = []
    market_value = 0.0
    cost_value = 0.0
    daily_pnl = 0.0
    priced_positions = 0
    for position in portfolio.get("positions", []):
        symbol = position["symbol"]
        quantity = float(position["quantity"])
        cost_price = float(position["cost_price"])
        quote = quotes.get(symbol)
        invested = round(cost_price * quantity, 2)
        row: dict[str, Any] = {
            "symbol": symbol,
            "quantity": quantity,
            "cost_price": cost_price,
            "cost_value": invested,
            "quote": quote.to_dict() if quote else None,
            "market_value": None,
            "unrealized_pnl": None,
            "unrealized_pnl_pct": None,
            "daily_pnl": None,
            "advice": quote_advice(quote),
        }
        cost_value += invested
        if quote and quote.price is not None:
            current_value = quote.price * quantity
            row["market_value"] = round(current_value, 2)
            row["unrealized_pnl"] = round(current_value - invested, 2)
            row["unrealized_pnl_pct"] = round((quote.price / cost_price - 1) * 100, 2) if cost_price else None
            market_value += current_value
            priced_positions += 1
            if quote.previous_close is not None:
                position_daily_pnl = (quote.price - quote.previous_close) * quantity
                row["daily_pnl"] = round(position_daily_pnl, 2)
                daily_pnl += position_daily_pnl
        rows.append(row)
    total_assets = cash + market_value
    return {
        "cash_balance": round(cash, 2),
        "cost_value": round(cost_value, 2),
        "market_value": round(market_value, 2),
        "total_assets": round(total_assets, 2),
        "unrealized_pnl": round(market_value - cost_value, 2),
        "daily_pnl": round(daily_pnl, 2),
        "priced_positions": priced_positions,
        "position_count": len(rows),
        "positions": rows,
    }


def quote_advice(quote: RealtimeQuote | None) -> str:
    if quote is None or quote.data_status == "unavailable" or quote.change_pct is None:
        return "行情暂不可用；不要依据旧价调整计划，先刷新或运行完整研究。"
    prefix = "最近可用行情：" if quote.data_status == "latest_available" else ""
    if quote.change_pct <= -5:
        return f"{prefix}当日跌幅显著：先核验公告、趋势和流动性，避免在风险未澄清前补仓。"
    if quote.change_pct <= -2:
        return f"{prefix}当日偏弱：检查是否跌破个人战法的失效条件，而不是只看成本价。"
    if quote.change_pct >= 5:
        return f"{prefix}当日波动显著：不把强势本身当信号，核验资金连续性与题材阶段。"
    if quote.change_pct >= 2:
        return f"{prefix}当日偏强：优先等趋势与成交额确认，避免追逐单日涨幅。"
    return f"{prefix}当日波动温和：可结合当前风格原型运行完整研究，再决定是否继续观察。"
