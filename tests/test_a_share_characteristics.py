from __future__ import annotations

import unittest

from app.schemas.report import MarketContext
from app.skills.a_share_characteristics import analyze_a_share_characteristics


def _context(**overrides: object) -> MarketContext:
    values: dict[str, object] = {
        "index_name": "上证指数",
        "index_change_pct": 1.0,
        "total_amount": 1_000_000_000_000,
        "advancers": 3500,
        "decliners": 1500,
        "limit_up_count": 80,
        "limit_down_count": 5,
        "hot_money_cycle": "发酵",
        "policy_themes": [],
        "failed_breakout_rate": 20.0,
        "yesterday_limit_up_premium": 2.0,
        "max_consecutive_boards": 5,
        "first_board_count": 50,
        "second_board_success_rate": 35.0,
        "strong_stock_return": 3.0,
        "sealed_limit_up_rate": 80.0,
        "one_price_limit_up_count": 6,
        "broken_limit_up_count": 20,
        "board_ladder": {"1板": 50, "2板": 18, "3板": 8, "4板以上": 4},
        "as_of": "2026-07-10",
    }
    values.update(overrides)
    return MarketContext(**values)


class AShareCharacteristicsTest(unittest.TestCase):
    def test_uses_seal_rate_one_price_and_board_ladder(self) -> None:
        insight = analyze_a_share_characteristics(_context())
        self.assertEqual(insight.stage, "封板强")
        self.assertTrue(insight.details["admitted"])
        self.assertEqual(insight.details["source_ids"], ["market-001"])

    def test_missing_ladder_preserves_verified_partial_evidence(self) -> None:
        insight = analyze_a_share_characteristics(_context(board_ladder={}))
        self.assertIn("梯队待核验", insight.stage)
        self.assertTrue(insight.details["admitted"])
        self.assertEqual(insight.details["coverage_status"], "partial")
        self.assertTrue(any("未按零值" in item for item in insight.evidence))

    def test_missing_core_field_remains_insufficient(self) -> None:
        insight = analyze_a_share_characteristics(_context(sealed_limit_up_rate=None))
        self.assertEqual(insight.stage, "数据不足")
        self.assertFalse(insight.details["admitted"])


if __name__ == "__main__":
    unittest.main()
