from __future__ import annotations

import unittest

from app.schemas.report import DailyPrice, MarketContext, MoneyFlowSnapshot
from app.skills.main_force_behavior import identify_main_force_behavior
from app.skills.money_making_effect import assess_money_making_effect
from app.skills.market_strategy_gate import select_market_eligible_playbooks
from app.skills.sentiment_cycle import identify_sentiment_cycle


class PartialVerifiedSkillTest(unittest.TestCase):
    def test_money_making_uses_verified_breakout_feedback_without_zero_fill(self) -> None:
        context = MarketContext(
            "上证指数", -0.5, 1_000_000_000_000, 1064, 4368, 27, 74, "未知", [],
            failed_breakout_rate=52.6,
            sealed_limit_up_rate=47.4,
            one_price_limit_up_count=5,
            broken_limit_up_count=30,
            as_of="2026-07-17",
        )
        insight = assess_money_making_effect(context)
        self.assertIn("部分核验", insight.stage)
        self.assertEqual(insight.details["coverage_status"], "partial")
        self.assertTrue(any("炸板率 52.6%" in item for item in insight.evidence))

    def test_main_force_uses_single_verified_vendor_measure_without_overclaiming(self) -> None:
        prices = [
            DailyPrice(f"2026-06-{day:02d}", 6.0, 6.2, 5.9, 6.0 + day / 100, 1_000_000 + day, 6_000_000, 4.0)
            for day in range(1, 21)
        ]
        flow = MoneyFlowSnapshot(948_000_000, None, None, "未知", 4.67, "未知", as_of="2026-07-17")
        insight = identify_main_force_behavior(prices, flow)
        self.assertIn("单口径净流入观察", insight.stage)
        self.assertEqual(insight.details["coverage_status"], "partial")
        self.assertTrue(any("未按零值" in item for item in insight.evidence))
        self.assertIn("不能进一步归因", insight.conclusion)

    def test_single_day_sentiment_is_visible_but_keeps_defensive_gate(self) -> None:
        context = MarketContext(
            "上证指数", -0.5, 1_000_000_000_000, 1064, 4368, 33, 74, "未知", [],
            failed_breakout_rate=43.1,
            sealed_limit_up_rate=56.9,
            one_price_limit_up_count=3,
            broken_limit_up_count=25,
            as_of="2026-07-17",
        )
        sentiment = identify_sentiment_cycle(context)
        self.assertEqual(sentiment.stage, "单日反馈（周期待积累）")
        self.assertEqual(sentiment.details["coverage_status"], "partial")
        gate = select_market_eligible_playbooks([sentiment])
        self.assertEqual(gate.details["allowed_playbooks"], ["institutional_value_dividend"])


if __name__ == "__main__":
    unittest.main()
