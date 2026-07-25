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
        insight = analyze_next_session_scenario(_prices(500))

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
        realtime_quote = {
            "trade_date": rows[-1].trade_date,
            "trade_time": "13:30:00",
            "data_status": "real_time",
        }
        first = analyze_next_session_scenario(rows, realtime_quote=realtime_quote)
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
        second = analyze_next_session_scenario(changed, realtime_quote=realtime_quote)

        self.assertEqual(first.details["excluded_incomplete_bar_date"], rows[-1].trade_date)
        self.assertEqual(second.details["excluded_incomplete_bar_date"], rows[-1].trade_date)
        self.assertEqual(first.details, second.details)

    def test_completed_current_day_bar_is_retained_after_market_close(self) -> None:
        rows = _prices(500)
        realtime_quote = {
            "trade_date": rows[-1].trade_date,
            "trade_time": "15:00:01",
            "data_status": "real_time",
        }

        insight = analyze_next_session_scenario(rows, realtime_quote=realtime_quote)

        self.assertEqual(insight.details["as_of"], rows[-1].trade_date)
        self.assertIsNone(insight.details["excluded_incomplete_bar_date"])
        self.assertEqual(insight.details["rate_basis"], "exact_state_match")

    def test_refuses_full_baseline_when_current_state_samples_are_insufficient(self) -> None:
        rows = _prices(120)
        last = rows[-1]
        rows[-1] = DailyPrice(
            last.trade_date,
            last.open,
            last.high + 10,
            last.low,
            last.close + 5,
            last.volume,
            last.amount,
            last.turnover_rate,
        )

        insight = analyze_next_session_scenario(rows)

        self.assertFalse(insight.details["available"])
        self.assertEqual(insight.details["sample_size"], 0)
        self.assertGreaterEqual(insight.details["eligible_outcome_count"], 30)
        self.assertTrue(insight.details["no_forward_lookahead"])
        self.assertEqual(insight.details["rate_basis"], "exact_state_match")
        self.assertNotIn("red_rate_pct", insight.details)
        self.assertIn("全样本涨跌分布与当前状态不等价", insight.conclusion)


if __name__ == "__main__":
    unittest.main()
