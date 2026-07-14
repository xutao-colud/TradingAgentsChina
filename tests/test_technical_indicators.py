from __future__ import annotations

import unittest

from app.data.providers.sample_provider import SampleMarketDataProvider
from app.indicators.technical import trend_snapshot


class TechnicalIndicatorsTest(unittest.TestCase):
    def test_snapshot_contains_deterministic_a_share_indicator_set(self) -> None:
        prices = SampleMarketDataProvider().get_daily_prices("600519", "2026-07-10", 120)
        snapshot = trend_snapshot(prices)

        self.assertIsNotNone(snapshot["macd_line"])
        self.assertIsNotNone(snapshot["boll_upper"])
        self.assertIsNotNone(snapshot["kdj_j"])
        self.assertIsNotNone(snapshot["cost_vwap"])
        self.assertIsNotNone(snapshot["cost_dominant_zone"])
        self.assertIsNotNone(snapshot["ma60"])
        self.assertIsNotNone(snapshot["ma120"])
        self.assertIsNotNone(snapshot["return_60d"])
        self.assertIsNotNone(snapshot["return_120d"])

    def test_short_history_does_not_invent_long_window_indicators(self) -> None:
        prices = SampleMarketDataProvider().get_daily_prices("600519", "2026-07-10", 5)
        snapshot = trend_snapshot(prices)

        self.assertIsNone(snapshot["boll_upper"])
        self.assertIsNone(snapshot["macd_line"])
        self.assertIsNone(snapshot["ma60"])
        self.assertIsNone(snapshot["ma120"])
        self.assertIsNone(snapshot["cost_vwap"])

    def test_thirty_bars_only_enable_short_cycle_indicators(self) -> None:
        prices = SampleMarketDataProvider().get_daily_prices("600519", "2026-07-10", 30)
        snapshot = trend_snapshot(prices)

        self.assertIsNotNone(snapshot["macd_line"])
        self.assertIsNotNone(snapshot["boll_upper"])
        self.assertIsNotNone(snapshot["kdj_j"])
        self.assertIsNone(snapshot["ma60"])
        self.assertIsNone(snapshot["ma120"])
        self.assertIsNone(snapshot["return_60d"])
        self.assertIsNone(snapshot["return_120d"])
        self.assertIsNone(snapshot["cost_vwap"])


if __name__ == "__main__":
    unittest.main()
