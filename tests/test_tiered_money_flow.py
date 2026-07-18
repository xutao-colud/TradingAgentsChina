from __future__ import annotations

import unittest

from app.schemas.report import MoneyFlowSnapshot
from app.skills.tiered_money_flow import analyze_tiered_money_flow


class TieredMoneyFlowTest(unittest.TestCase):
    def test_detects_large_small_divergence_without_claiming_identity(self) -> None:
        flow = MoneyFlowSnapshot(
            60_000_000, 40_000_000, 0, "未知", 3, "未知",
            large_net_inflow=30_000_000,
            medium_net_inflow=-10_000_000,
            small_net_inflow=-20_000_000,
            as_of="2026-07-13 14:30:00",
        )
        result = analyze_tiered_money_flow(flow)
        self.assertEqual(result.stage, "大单净流入/中小单净流出")
        self.assertIn("不是主力身份认定", result.conclusion)
        self.assertTrue(any("供应商" in item for item in result.risks))
        self.assertTrue(result.details["admitted"])

    def test_aggregate_flow_without_tiers_is_provider_scope_not_fake_zero(self) -> None:
        result = analyze_tiered_money_flow(MoneyFlowSnapshot(1, None, 0, "未知", 1, "未知"))
        self.assertEqual(result.stage, "供应商未覆盖分档")
        self.assertFalse(result.details["admitted"])
        self.assertEqual(result.details["coverage_status"], "provider_not_covered")

    def test_no_flow_at_all_is_insufficient(self) -> None:
        result = analyze_tiered_money_flow(MoneyFlowSnapshot(None, None, 0, "未知", 1, "未知"))
        self.assertEqual(result.stage, "数据不足")


if __name__ == "__main__":
    unittest.main()
