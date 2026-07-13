from __future__ import annotations

import unittest

from app.schemas.report import DailyPrice
from app.skills.turnover_continuity import analyze_turnover_continuity


def prices(turnovers: list[float | None]) -> list[DailyPrice]:
    return [
        DailyPrice(f"2026-07-{index + 1:02d}", 10, 11, 9, 10 + index * 0.1, 1000, 10_000_000, turnover)
        for index, turnover in enumerate(turnovers)
    ]


class TurnoverContinuityTest(unittest.TestCase):
    def test_detects_multi_day_turnover_expansion(self) -> None:
        insight = analyze_turnover_continuity(prices([1, 1.1, 1.2, 1.4, 1.8, 2.2, 2.8, 3.4, 4.1, 5.0]))
        self.assertEqual(insight.stage, "持续放大")
        self.assertTrue(insight.details["admitted"])
        self.assertIn("5d_change_pct", insight.details)

    def test_missing_turnover_is_not_zero_filled(self) -> None:
        insight = analyze_turnover_continuity(prices([None, None, 1.2, None, 1.3]))
        self.assertEqual(insight.stage, "数据不足")
        self.assertFalse(insight.details["admitted"])

    def test_zero_history_baseline_is_not_relabelled_as_flat_turnover(self) -> None:
        insight = analyze_turnover_continuity(prices([0, 0, 0, 0, 1]))

        self.assertEqual(insight.stage, "数据不足")
        self.assertFalse(insight.details["admitted"])
        self.assertIn("基线", insight.conclusion)


if __name__ == "__main__":
    unittest.main()
