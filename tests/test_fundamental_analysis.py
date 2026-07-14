from __future__ import annotations

import unittest

from app.indicators.fundamental import analyze_fundamental_quality
from app.schemas.report import FundamentalSnapshot


class FundamentalAnalysisTest(unittest.TestCase):
    def test_dupont_and_cash_conversion_are_deterministic(self) -> None:
        snapshot = FundamentalSnapshot(0, 0, 0, 0, 0, 0, 0, 0, "稳定", revenue=200, net_income=20, operating_cash_flow=30, total_assets=100, total_equity=50, accounts_receivable=20, inventory=10, peer_medians={"roe": 10})
        analysis = analyze_fundamental_quality(snapshot)

        self.assertAlmostEqual(analysis.dupont_margin, 0.1)
        self.assertAlmostEqual(analysis.asset_turnover, 2.0)
        self.assertAlmostEqual(analysis.equity_multiplier, 2.0)
        self.assertAlmostEqual(analysis.dupont_roe, 0.4)
        self.assertAlmostEqual(analysis.cash_conversion, 1.5)
        self.assertEqual(analysis.peer_comparison["roe"], -10)

    def test_missing_statements_do_not_create_industry_comparison(self) -> None:
        analysis = analyze_fundamental_quality(FundamentalSnapshot(0, 0, 0, 0, 0, 0, 0, 0, "稳定"))

        self.assertIsNone(analysis.dupont_roe)
        self.assertEqual(analysis.peer_comparison, {})
        self.assertTrue(any("同业" in item for item in analysis.unavailable_reasons))

    def test_explicit_dupont_fields_are_preserved_without_recomputation(self) -> None:
        snapshot = FundamentalSnapshot(
            0, 0, 0, 0, 0, 0, 0, 0, "稳定",
            revenue=200,
            net_income=20,
            total_assets=100,
            total_equity=50,
            net_profit_margin=0.12,
            asset_turnover=1.8,
            equity_multiplier=2.1,
        )

        analysis = analyze_fundamental_quality(snapshot)

        self.assertEqual(analysis.dupont_margin, 0.12)
        self.assertEqual(analysis.asset_turnover, 1.8)
        self.assertEqual(analysis.equity_multiplier, 2.1)


if __name__ == "__main__":
    unittest.main()
