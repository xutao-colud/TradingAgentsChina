from __future__ import annotations

import unittest

from app.schemas.report import MarketContext
from app.skills.a_share_characteristics import analyze_a_share_characteristics


class AShareCharacteristicsTest(unittest.TestCase):
    def test_uses_seal_rate_one_price_and_board_ladder(self) -> None:
        context = MarketContext(
            "上证指数", 1.0, 1_000_000_000_000, 3500, 1500, 80, 5, "发酵", [],
            failed_breakout_rate=20.0,
            yesterday_limit_up_premium=2.0,
            max_consecutive_boards=5,
            first_board_count=50,
            second_board_success_rate=35.0,
            strong_stock_return=3.0,
            sealed_limit_up_rate=80.0,
            one_price_limit_up_count=6,
            broken_limit_up_count=20,
            board_ladder={"1板": 50, "2板": 18, "3板": 8, "4板以上": 4},
            as_of="2026-07-10",
        )

        insight = analyze_a_share_characteristics(context)

        self.assertEqual(insight.stage, "封板强")
        self.assertTrue(insight.details["admitted"])
        self.assertEqual(insight.details["source_ids"], ["market-001"])

    def test_missing_ladder_is_not_interpreted_as_zero(self) -> None:
        context = MarketContext("上证指数", 0, 0, 0, 0, 0, 0, "未知", [], as_of="2026-07-10")
        insight = analyze_a_share_characteristics(context)
        self.assertEqual(insight.stage, "数据不足")
        self.assertFalse(insight.details["admitted"])


if __name__ == "__main__":
    unittest.main()
