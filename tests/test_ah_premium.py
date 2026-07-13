from __future__ import annotations

import unittest

from app.schemas.report import AhPremiumSnapshot, DataQualityReport
from app.skills.ah_premium import analyze_ah_premium


class AhPremiumTest(unittest.TestCase):
    def test_verified_observation_remains_relative_valuation_evidence(self) -> None:
        snapshot = AhPremiumSnapshot(
            "verified", "2026-07-10", "600036.SH", "03968.HK", 45.8, 41.2, 1.21, 21.4, "ah-premium-001"
        )
        quality = DataQualityReport("tushare", "ah_premium", "passed", 1, 1, 1.0, "2026-07-10")

        insight = analyze_ah_premium(snapshot, [quality])

        self.assertTrue(insight.details["admitted"])
        self.assertEqual(insight.details["premium_pct"], 21.4)
        self.assertIn("不单独形成交易结论", insight.strategy)

    def test_not_applicable_has_no_fabricated_premium(self) -> None:
        snapshot = AhPremiumSnapshot("not_applicable", "2026-07-10", "600519.SH")
        insight = analyze_ah_premium(snapshot, [])
        self.assertEqual(insight.stage, "不适用")
        self.assertFalse(insight.details["admitted"])


if __name__ == "__main__":
    unittest.main()
