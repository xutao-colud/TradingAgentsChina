from __future__ import annotations

import unittest
from datetime import date, timedelta

from app.schemas.report import DailyPrice
from app.skills.price_observation_zones import analyze_price_observation_zones


def _range_prices(count: int) -> list[DailyPrice]:
    start = date(2025, 1, 1)
    pattern = [5.82, 5.90, 6.02, 6.18, 6.42, 6.25, 6.08, 5.96]
    rows: list[DailyPrice] = []
    for index in range(count):
        close = pattern[index % len(pattern)]
        if index == count - 1:
            close = 6.00
        rows.append(
            DailyPrice(
                trade_date=(start + timedelta(days=index)).isoformat(),
                open=close - 0.03,
                high=close + 0.10,
                low=close - 0.10,
                close=close,
                volume=1_000_000 + (index % 8) * 100_000,
                amount=close * 1_000_000,
                turnover_rate=2.0,
            )
        )
    return rows


class PriceObservationZonesTest(unittest.TestCase):
    def test_builds_short_and_medium_observation_zones(self) -> None:
        insight = analyze_price_observation_zones(_range_prices(120))

        self.assertEqual(insight.details["mode"], "price_observation_zones")
        self.assertTrue(insight.details["observational_only"])
        self.assertFalse(insight.details["admitted"])
        self.assertEqual(insight.details["current_price"], 6.0)
        self.assertIsNotNone(insight.details["short_term"]["support_zone"])
        self.assertIsNotNone(insight.details["short_term"]["resistance_zone"])
        self.assertTrue(insight.details["medium_term"]["available"])
        self.assertFalse(insight.details["long_term"]["available"])
        self.assertIsNone(insight.details["long_term"]["target_zone"])

    def test_short_history_does_not_create_price_levels(self) -> None:
        insight = analyze_price_observation_zones(_range_prices(10))

        self.assertEqual(insight.stage, "数据不足")
        self.assertFalse(insight.details["available"])
        self.assertNotIn("short_term", insight.details)


if __name__ == "__main__":
    unittest.main()
