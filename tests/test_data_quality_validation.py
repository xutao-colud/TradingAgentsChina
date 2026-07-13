from __future__ import annotations

import unittest

from app.data.quality import validate_dataset_records
from app.schemas.report import DailyPrice, DragonTigerRecord, MarginFinancingRecord


class DataQualityValidationTest(unittest.TestCase):
    def test_invalid_ohlc_and_future_date_are_rejected(self) -> None:
        records = [DailyPrice("2026-07-11", 10, 9, 11, 10, 100, 1000, 1)]

        valid, report = validate_dataset_records(
            provider="tushare",
            dataset="daily_prices",
            records=records,
            analysis_date="2026-07-10",
        )

        self.assertEqual(valid, [])
        self.assertEqual(report.status, "failed")
        self.assertTrue(report.blocking)
        self.assertEqual({item.code for item in report.issues}, {"future_date", "invalid_ohlc_range"})

    def test_dragon_tiger_requires_same_trade_date(self) -> None:
        records = [DragonTigerRecord("2026-07-09", "日涨幅偏离", 100, 50, source_id="dragon-tiger-001")]

        valid, report = validate_dataset_records(
            provider="tushare",
            dataset="dragon_tiger",
            records=records,
            analysis_date="2026-07-10",
        )

        self.assertEqual(valid, [])
        self.assertEqual(report.issues[0].code, "analysis_date_mismatch")

    def test_negative_margin_balance_is_rejected_without_neutral_fallback(self) -> None:
        records = [MarginFinancingRecord("2026-07-10", -1, 0, 10, 5, "margin-001")]

        valid, report = validate_dataset_records(
            provider="tushare",
            dataset="margin_financing",
            records=records,
            analysis_date="2026-07-10",
        )

        self.assertEqual(valid, [])
        self.assertEqual(report.status, "failed")
        self.assertFalse(report.blocking)


if __name__ == "__main__":
    unittest.main()
