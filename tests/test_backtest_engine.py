from __future__ import annotations

import unittest

from app.backtest.engine import BacktestSpec, run_backtest
from app.schemas.report import DailyPrice, StockProfile


def bars(count: int = 12) -> list[DailyPrice]:
    return [
        DailyPrice(f"2026-07-{index + 1:02d}", 10 + index, 10.5 + index, 9.5 + index, 10 + index, 1_000_000, 100_000_000, 2)
        for index in range(count)
    ]


class BacktestEngineTest(unittest.TestCase):
    def test_signal_history_never_contains_future_bar_and_fill_is_next_open(self) -> None:
        observed_lengths: list[int] = []

        def entry(history):
            observed_lengths.append(len(history))
            return len(history) == 2

        result = run_backtest(
            StockProfile("600000.SH", "测试", "银行", "main"), bars(),
            BacktestSpec("test", "two bars then hold", entry, lambda history: len(history) == 5, 10),
        )
        self.assertTrue(all(length <= len(bars()) for length in observed_lengths))
        self.assertEqual(result.trades[0].entry_date, "2026-07-03")
        self.assertEqual(result.trades[0].exit_date, "2026-07-06")
        self.assertGreater(result.trades[0].entry_price, bars()[2].open)
        self.assertLess(result.trades[0].exit_price, bars()[5].open)

    def test_t_plus_one_prevents_same_bar_exit(self) -> None:
        result = run_backtest(
            StockProfile("600000.SH", "测试", "银行", "main"), bars(),
            BacktestSpec("test", "immediate exit request", lambda history: len(history) == 1, lambda history: True, 10),
        )
        self.assertGreaterEqual(result.trades[0].holding_bars, 1)
        self.assertNotEqual(result.trades[0].entry_date, result.trades[0].exit_date)

    def test_small_sample_does_not_display_empirical_win_rate(self) -> None:
        result = run_backtest(
            StockProfile("600000.SH", "测试", "银行", "main"), bars(),
            BacktestSpec("test", "small sample", lambda history: len(history) == 1, lambda history: len(history) >= 3, 10),
        )
        self.assertEqual(result.evidence_status, "insufficient_sample")
        self.assertIsNone(result.positive_trade_rate)
        self.assertTrue(any("不展示经验正收益比例" in item for item in result.limitations))

    def test_point_in_time_dataset_symbol_and_sources_are_enforced(self) -> None:
        profile = StockProfile("600000.SH", "测试", "银行", "main")
        with self.assertRaises(ValueError):
            run_backtest(
                profile,
                bars(),
                BacktestSpec("test", "mismatch", lambda history: False, lambda history: False, 5, dataset_symbol="000001.SZ"),
            )
        result = run_backtest(
            profile,
            bars(),
            BacktestSpec(
                "test",
                "traceable",
                lambda history: False,
                lambda history: False,
                5,
                dataset_symbol="600000.SH",
                source_ids=("fund-001", "valuation-001"),
            ),
        )
        self.assertEqual(result.source_ids, ["fund-001", "valuation-001"])

    def test_regime_breakdown_and_stress_slippage_remain_active_for_extended_specs(self) -> None:
        profile = StockProfile("600000.SH", "测试", "银行", "main")
        spec = BacktestSpec(
            "extended",
            "two dated setups",
            lambda history: len(history) in {1, 5},
            lambda history: len(history) in {3, 7},
            10,
            dataset_symbol="600000.SH",
            source_ids=("pit-001",),
        )
        input_bars = bars()
        regimes = {
            item.trade_date: "启动" if index < 4 else "退潮"
            for index, item in enumerate(input_bars)
        }
        normal = run_backtest(profile, input_bars, spec, regimes=regimes)
        stressed = run_backtest(profile, input_bars, spec, regimes=regimes, stress=True)

        self.assertEqual({item.market_regime for item in normal.regime_summaries}, {"启动", "退潮"})
        self.assertGreater(stressed.trades[0].entry_price, normal.trades[0].entry_price)
        self.assertLess(stressed.trades[0].exit_price, normal.trades[0].exit_price)


if __name__ == "__main__":
    unittest.main()
