from __future__ import annotations

import unittest

from app.schemas.report import FundamentalSnapshot, MarketContext, MarketSentimentObservation, StockProfile


class DomainSignalContractsTest(unittest.TestCase):
    def test_optional_domain_inputs_are_typed_and_default_safe(self) -> None:
        profile = StockProfile("600519.SH", "测试", "食品饮料", "main", concepts=["消费复苏"])
        fundamentals = FundamentalSnapshot(1, 2, 3, 4, 5, 6, 7, 0.8, "稳定", revenue=100, net_income=10, total_assets=200, total_equity=100)
        context = MarketContext("上证", 0, 0, 0, 0, 0, 0, "未知", [], sentiment_history=[MarketSentimentObservation("2026-07-10", 30, 10, 20, 1, 3, 20, 30, 2)])

        self.assertEqual(profile.concepts, ["消费复苏"])
        self.assertEqual(fundamentals.total_equity, 100)
        self.assertEqual(context.sentiment_history[0].limit_up_count, 30)


if __name__ == "__main__":
    unittest.main()
