from __future__ import annotations

import unittest

from app.indicators.market_breadth import evaluate_market_breadth_confirmation
from app.schemas.report import MarketContext
from app.skills.market_breadth_confirmation import confirm_market_breadth


class MarketBreadthConfirmationTest(unittest.TestCase):
    def test_weighted_index_strength_is_rejected_when_equal_weight_breadth_is_weak(self) -> None:
        context = MarketContext(
            "上证指数", 1.2, 900_000_000_000, 1400, 3500, 25, 50, "数据不足", [],
            median_stock_change_pct=-1.1,
            amount_weighted_change_pct=0.9,
            top_amount_concentration_pct=36,
            as_of="2026-07-16",
        )

        result = evaluate_market_breadth_confirmation(context)
        insight = confirm_market_breadth(context)

        self.assertEqual(result.stage, "权重背离")
        self.assertLess(result.score_adjustment, 0)
        self.assertTrue(any("权重股" in item for item in result.risks))
        self.assertEqual(insight.stage, "权重背离")
        self.assertEqual(insight.details["source_ids"], ["market-001"])

    def test_missing_cross_section_facts_remains_insufficient(self) -> None:
        context = MarketContext("上证指数", 1, 1, 2, 1, 1, 0, "数据不足", [], as_of="2026-07-16")

        result = evaluate_market_breadth_confirmation(context)

        self.assertEqual(result.stage, "数据不足")
        self.assertIn("median_stock_change_pct", result.missing_fields)


if __name__ == "__main__":
    unittest.main()
