from __future__ import annotations

import unittest

from app.market.realtime import RealtimeQuote
from app.portfolio.snapshot import build_portfolio_snapshot, quote_advice


class PortfolioSnapshotTest(unittest.TestCase):
    def test_builds_pnl_and_daily_change_from_quotes(self) -> None:
        quote = RealtimeQuote("600519.SH", "贵州茅台", 1515.0, 1500.0, 1.0, 1, 1, "2026-07-11", "14:30:00")
        snapshot = build_portfolio_snapshot(
            {"cash_balance": 5000, "positions": [{"symbol": "600519.SH", "quantity": 10, "cost_price": 1480}]},
            {"600519.SH": quote},
        )
        self.assertEqual(snapshot["market_value"], 15150.0)
        self.assertEqual(snapshot["unrealized_pnl"], 350.0)
        self.assertEqual(snapshot["daily_pnl"], 150.0)

    def test_warns_when_quote_is_unavailable_or_large_drop(self) -> None:
        unavailable = RealtimeQuote("600519.SH", None, None, None, None, None, None, None, None, data_status="unavailable")
        self.assertIn("暂不可用", quote_advice(unavailable))
        dropped = RealtimeQuote("600519.SH", "贵州茅台", 1400, 1500, -6.67, 1, 1, "2026-07-11", "14:30:00")
        self.assertIn("跌幅显著", quote_advice(dropped))
