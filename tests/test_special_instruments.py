from __future__ import annotations

import unittest

from app.rules.special_instruments import ConvertibleBondSnapshot, assess_convertible_bond, assess_listing_stage
from app.rules.trading_rules import normalize_symbol
from app.schemas.report import StockProfile


class SpecialInstrumentTest(unittest.TestCase):
    def test_listing_stage_uses_dated_metadata(self) -> None:
        profile = StockProfile("001337.SZ", "测试新股", "电子", "main", list_date="2026-07-10")
        result = assess_listing_stage(profile, "2026-07-13")
        self.assertEqual(result.stage, "新股阶段")
        self.assertEqual(result.details["listed_days"], 3)

    def test_missing_listing_date_is_not_guessed(self) -> None:
        result = assess_listing_stage(StockProfile("600000.SH", "测试", "银行", "main"), "2026-07-13")
        self.assertEqual(result.stage, "数据不足")

    def test_convertible_bond_reports_premium_and_risks(self) -> None:
        result = assess_convertible_bond(ConvertibleBondSnapshot(
            "123001.SZ", "测试转债", "2026-07-13 14:30:00", 150, 10, 10, 200_000_000, 5_000_000,
            source_ids=["cb-001"],
        ))
        self.assertEqual(result.stage, "风险约束较多")
        self.assertAlmostEqual(result.details["premium_pct"], 50)
        self.assertGreaterEqual(len(result.risks), 3)

    def test_convertible_bond_exchange_prefixes_are_configured(self) -> None:
        self.assertEqual(normalize_symbol("123001"), "123001.SZ")
        self.assertEqual(normalize_symbol("113001"), "113001.SH")


if __name__ == "__main__":
    unittest.main()
