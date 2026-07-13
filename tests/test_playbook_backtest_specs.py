from __future__ import annotations

import unittest
from datetime import date, timedelta

from app.backtest.datasets import (
    ConsensusBacktestObservation,
    DividendBacktestObservation,
    FundamentalBacktestObservation,
    MarketBacktestObservation,
    PointInTimeDataset,
    StockBehaviorObservation,
    ThemeBacktestObservation,
    ThemeMembershipObservation,
    ValuationBacktestObservation,
)
from app.backtest.playbook_specs import (
    assess_dataset_coverage,
    build_playbook_spec,
    build_price_playbook_spec,
    describe_backtest_capability,
)
from app.schemas.report import DailyPrice


class PlaybookBacktestSpecsTest(unittest.TestCase):
    def test_all_public_playbooks_have_codified_backtest_builders(self) -> None:
        for playbook_id in (
            "trend_core",
            "hot_money_leader",
            "institutional_growth",
            "institutional_value_dividend",
        ):
            capability = describe_backtest_capability(playbook_id)
            self.assertTrue(capability.supported)
            self.assertTrue(capability.input_mode)
        spec = build_price_playbook_spec("trend_core")
        self.assertEqual(spec.playbook_id, "trend_core")
        self.assertGreater(spec.maximum_holding_bars, 0)

    def test_non_price_playbooks_still_reject_price_only_or_incomplete_data(self) -> None:
        with self.assertRaises(ValueError):
            build_price_playbook_spec("institutional_growth")
        incomplete = PointInTimeDataset(
            symbol="600000.SH",
            fundamentals=[_fundamental("2026-07-01", profit_growth=12)],
        )
        self.assertEqual(
            assess_dataset_coverage("institutional_growth", incomplete),
            ["consensus_history", "valuation_history"],
        )
        with self.assertRaises(ValueError):
            build_playbook_spec("institutional_growth", incomplete)

    def test_hot_money_rule_uses_historical_membership_not_current_membership(self) -> None:
        history = tuple(_bars(10, date(2026, 7, 1)))
        as_of = history[-1].trade_date
        hidden_membership = _hot_money_dataset(known_at="2026-07-20", as_of=as_of)
        visible_membership = _hot_money_dataset(known_at="2026-07-01", as_of=as_of)

        hidden_spec = build_playbook_spec("hot_money_leader", hidden_membership)
        visible_spec = build_playbook_spec("hot_money_leader", visible_membership)

        self.assertFalse(hidden_spec.entry_rule(history))
        self.assertTrue(visible_spec.entry_rule(history))
        self.assertIn("theme-membership-001", visible_spec.source_ids)

    def test_growth_rule_cannot_see_future_report_or_consensus(self) -> None:
        history = tuple(_bars(25, date(2026, 7, 1)))
        dataset = PointInTimeDataset(
            symbol="600000.SH",
            fundamentals=[
                _fundamental("2026-07-01", profit_growth=-5),
                _fundamental("2026-07-20", profit_growth=20),
            ],
            consensus=[
                ConsensusBacktestObservation("2026-07-01", "600000.SH", -8, 5, "consensus-old"),
                ConsensusBacktestObservation("2026-07-20", "600000.SH", 3, 15, "consensus-new"),
            ],
            valuations=[
                ValuationBacktestObservation(item.trade_date, "600000.SH", 25, 2, f"valuation-{index}")
                for index, item in enumerate(history, start=1)
            ],
        )
        spec = build_playbook_spec("institutional_growth", dataset)

        self.assertFalse(spec.entry_rule(history[:19]))
        self.assertTrue(spec.entry_rule(history[:20]))
        self.assertEqual(dataset.latest_fundamental("2026-07-19").source_id, "fund-2026-07-01")
        self.assertEqual(dataset.latest_fundamental("2026-07-20").source_id, "fund-2026-07-20")

    def test_value_dividend_rule_requires_three_statements_valuation_and_announced_dividend(self) -> None:
        history = tuple(_bars(25, date(2026, 7, 1)))
        dataset = PointInTimeDataset(
            symbol="600000.SH",
            fundamentals=[_fundamental("2026-07-01", profit_growth=8)],
            valuations=[
                ValuationBacktestObservation(item.trade_date, "600000.SH", 18, 1.8, f"valuation-{index}")
                for index, item in enumerate(history, start=1)
            ],
            dividends=[DividendBacktestObservation("2026-07-20", "600000.SH", 0.5, 3.0, 45, "dividend-001")],
        )
        spec = build_playbook_spec("institutional_value_dividend", dataset)

        self.assertFalse(spec.entry_rule(history[:19]))
        self.assertTrue(spec.entry_rule(history[:20]))
        self.assertIn("dividend-001", spec.source_ids)

    def test_dataset_rejects_impossible_financial_timeline(self) -> None:
        with self.assertRaises(ValueError):
            PointInTimeDataset(
                symbol="600000.SH",
                fundamentals=[
                    FundamentalBacktestObservation(
                        "600000.SH", "2026-09-30", "2026-07-01", 10, 10, 10,
                        100, 80, 1000, 400, 500, False, "invalid-fund",
                    )
                ],
            )


def _bars(count: int, start: date) -> list[DailyPrice]:
    return [
        DailyPrice(
            (start + timedelta(days=index)).isoformat(),
            10 + index * 0.1,
            10.3 + index * 0.1,
            9.8 + index * 0.1,
            10.2 + index * 0.1,
            1_000_000,
            100_000_000,
            2,
        )
        for index in range(count)
    ]


def _fundamental(announced_at: str, profit_growth: float) -> FundamentalBacktestObservation:
    return FundamentalBacktestObservation(
        symbol="600000.SH",
        period_end="2026-06-30",
        announced_at=announced_at,
        revenue_growth_yoy=15,
        profit_growth_yoy=profit_growth,
        roe=12,
        operating_cash_flow=120,
        net_income=100,
        total_assets=1000,
        total_liabilities=450,
        total_equity=550,
        announcement_risk=False,
        source_id=f"fund-{announced_at}",
    )


def _hot_money_dataset(known_at: str, as_of: str) -> PointInTimeDataset:
    return PointInTimeDataset(
        symbol="600000.SH",
        market=[MarketBacktestObservation(as_of, "发酵", 60, 5, 15, "market-001")],
        themes=[ThemeBacktestObservation(as_of, "机器人", "扩散", 75, "theme-001")],
        memberships=[ThemeMembershipObservation("600000.SH", "机器人", "2026-07-01", None, known_at, "theme-membership-001")],
        stock_behavior=[StockBehaviorObservation(as_of, "600000.SH", "strong", 2, 20_000_000, 1, "stock-behavior-001")],
    )


if __name__ == "__main__":
    unittest.main()
