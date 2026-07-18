from __future__ import annotations

import unittest
from datetime import date, timedelta

from app.schemas.report import DailyPrice
from app.skills.next_session_scenario import analyze_next_session_scenario


def _prices(count: int, step: float = 0.05) -> list[DailyPrice]:
    start = date(2025, 1, 1)
    rows: list[DailyPrice] = []
    close = 5.0
    for index in range(count):
        close += step
        rows.append(
            DailyPrice(
                trade_date=(start + timedelta(days=index)).isoformat(),
                open=close - step / 2,
                high=close + 0.08,
                low=close - 0.08,
                close=close,
                volume=1_000_000 + index * 1_000,
                amount=close * 1_000_000,
                turnover_rate=2.0,
            )
        )
    return rows


class NextSessionScenarioTest(unittest.TestCase):
    def test_reports_observed_frequency_with_sample_provenance(self) -> None:
        insight = analyze_next_session_scenario(_prices(120))

        self.assertEqual(insight.details["mode"], "next_session_scenario")
        self.assertTrue(insight.details["observational_only"])
        self.assertTrue(insight.details["no_forward_lookahead"])
        self.assertGreaterEqual(insight.details["sample_size"], 30)
        self.assertAlmostEqual(
            insight.details["red_rate_pct"]
            + insight.details["flat_rate_pct"]
            + insight.details["green_rate_pct"],
            100.0,
            places=1,
        )
        self.assertEqual(insight.details["source_ids"], ["price-001"])
        self.assertFalse(insight.details["admitted"])

    def test_refuses_to_invent_rates_when_history_is_short(self) -> None:
        insight = analyze_next_session_scenario(_prices(15))

        self.assertEqual(insight.stage, "样本不足")
        self.assertFalse(insight.details["available"])
        self.assertNotIn("red_rate_pct", insight.details)

    def test_current_bar_is_never_used_as_its_own_outcome(self) -> None:
        rows = _prices(120)
        first = analyze_next_session_scenario(rows)
        changed = list(rows)
        last = changed[-1]
        changed[-1] = DailyPrice(
            last.trade_date,
            last.open,
            last.high + 10,
            last.low,
            last.close + 5,
            last.volume,
            last.amount,
            last.turnover_rate,
        )
        second = analyze_next_session_scenario(changed)

        self.assertEqual(first.details["sample_end"], rows[-1].trade_date)
        self.assertEqual(second.details["sample_end"], rows[-1].trade_date)
        self.assertEqual(first.details["sample_size"], second.details["sample_size"])


if __name__ == "__main__":
    unittest.main()
