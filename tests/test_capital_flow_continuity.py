from __future__ import annotations

import unittest

from app.schemas.report import CapitalFlowObservation, DailyPrice
from app.skills.capital_flow_continuity import analyze_capital_flow_continuity


def _prices(closes: list[float]) -> list[DailyPrice]:
    return [
        DailyPrice(f"2026-07-{index + 1:02d}", close, close, close, close, 1_000_000, 10_000_000, 1.0)
        for index, close in enumerate(closes)
    ]


def _history(main_flows: list[float], northbound: list[float] | None = None) -> list[CapitalFlowObservation]:
    northbound = northbound or [100.0] * len(main_flows)
    return [
        CapitalFlowObservation(
            trade_date=f"2026-07-{index + 1:02d}",
            main_net_inflow=flow,
            northbound_holding_change=northbound[index],
            margin_balance=1_000 + index * 10,
            source_ids=["flow-history-001", "margin-history-001", "northbound-history-001"],
        )
        for index, flow in enumerate(main_flows)
    ]


class CapitalFlowContinuityTest(unittest.TestCase):
    def test_calculates_three_and_five_day_continuity(self) -> None:
        result = analyze_capital_flow_continuity(
            _prices([10, 10.1, 10.2, 10.3, 10.4]),
            _history([1_000_000, 2_000_000, 3_000_000, 4_000_000, 5_000_000]),
        )

        self.assertEqual(result.stage, "主力连续净流入")
        self.assertEqual(result.details["main_streak_days"], 5)
        self.assertEqual(result.details["northbound_streak_days"], 5)
        self.assertEqual(result.details["margin_balance_streak_days"], 4)
        self.assertEqual(result.details["cumulative_main_flow"]["3d"], 12_000_000)
        self.assertEqual(result.details["cumulative_main_flow"]["5d"], 15_000_000)

    def test_detects_price_up_flow_out_divergence(self) -> None:
        result = analyze_capital_flow_continuity(
            _prices([10, 10.2, 10.4, 10.6, 10.8]),
            _history([-3_000_000] * 5),
        )

        self.assertEqual(result.stage, "价涨资金流出背离")
        self.assertEqual(result.details["divergence_type"], "price_up_flow_out")
        self.assertEqual(result.details["divergence_window"], 5)

    def test_missing_day_breaks_streak_instead_of_joining_records(self) -> None:
        history = _history([1_000_000] * 5)
        history[3] = CapitalFlowObservation("2026-07-04", None, 100, 1_030, ["margin-history-001"])
        result = analyze_capital_flow_continuity(_prices([10, 10.1, 10.2, 10.3, 10.4]), history)

        self.assertEqual(result.details["main_streak_days"], 1)
        self.assertIsNone(result.details["cumulative_main_flow"]["3d"])

    def test_empty_history_is_explicitly_insufficient(self) -> None:
        result = analyze_capital_flow_continuity(_prices([10]), [])

        self.assertEqual(result.stage, "数据不足")

    def test_one_verified_day_is_reported_as_accumulating(self) -> None:
        result = analyze_capital_flow_continuity(_prices([10]), _history([1_000_000]))

        self.assertEqual(result.stage, "样本积累中")
        self.assertEqual(result.details["observations"], 1)
        self.assertEqual(result.details["coverage_status"], "accumulating")

    def test_two_verified_days_are_reported_as_accumulating_not_zero_data(self) -> None:
        history = [
            CapitalFlowObservation("2026-07-16", 10_000_000, source_ids=["flow-history-cache-001"]),
            CapitalFlowObservation("2026-07-17", -3_000_000, source_ids=["flow-history-cache-001"]),
        ]

        result = analyze_capital_flow_continuity([], history)

        self.assertEqual(result.stage, "样本积累中")
        self.assertEqual(result.details["observations"], 2)
        self.assertEqual(result.details["coverage_status"], "accumulating")
        self.assertEqual(result.score, 50)

    def test_unaligned_dates_are_not_joined(self) -> None:
        history = [
            CapitalFlowObservation(f"2026-06-{index + 1:02d}", 1_000_000, 100, 1_000 + index, ["flow-history-001"])
            for index in range(5)
        ]
        result = analyze_capital_flow_continuity(_prices([10, 10.1, 10.2, 10.3, 10.4]), history)

        self.assertEqual(result.stage, "数据不足")
        self.assertEqual(result.details["aligned_observations"], 0)


if __name__ == "__main__":
    unittest.main()
