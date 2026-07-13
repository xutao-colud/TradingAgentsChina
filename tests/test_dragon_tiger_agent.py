from __future__ import annotations

import unittest

from app.agents.dragon_tiger_agent import analyze_dragon_tiger
from app.schemas.report import AshareMarketSignals, DailyPrice, DragonTigerRecord, DragonTigerSeatRecord


class DragonTigerAgentTest(unittest.TestCase):
    def test_disclosed_records_are_traceable_and_not_a_return_claim(self) -> None:
        finding = analyze_dragon_tiger(AshareMarketSignals("verified", dragon_tiger=[DragonTigerRecord("2026-07-10", "日涨幅偏离", 30_000_000, 10_000_000, source_id="dragon-tiger-001")]))

        self.assertEqual(finding.source_ids, ["dragon-tiger-001"])
        self.assertTrue(finding.counterpoints)
        self.assertTrue(finding.invalidation_conditions)
        self.assertIn("不等同于后续走势判断", finding.conclusion)

    def test_missing_disclosure_does_not_create_a_signal(self) -> None:
        finding = analyze_dragon_tiger(AshareMarketSignals("unavailable"))

        self.assertEqual(finding.confidence, 0.0)
        self.assertEqual(finding.source_ids, [])

    def test_seat_types_concentration_reason_and_observed_after_effect_are_explicit(self) -> None:
        current_seats = [
            DragonTigerSeatRecord("2026-07-10", "当日换手率达到20%", "机构专用", "buy", 80, 5, 75, source_id="dragon-tiger-001"),
            DragonTigerSeatRecord("2026-07-10", "当日换手率达到20%", "测试证券营业部", "buy", 20, 5, 15, source_id="dragon-tiger-001"),
        ]
        record = DragonTigerRecord(
            "2026-07-10", "当日换手率达到20%", 90, 75,
            source_id="dragon-tiger-001", seat_records=current_seats,
        )
        history = [
            DragonTigerSeatRecord(f"2026-07-0{day}", "换手率", "机构专用", "buy", 10, 0, 10, source_id="dragon-tiger-history-001")
            for day in (1, 3, 5)
        ]
        prices = [
            DailyPrice(f"2026-07-{day:02d}", 10 + day, 11 + day, 9 + day, 10 + day, 100, 1000, 1)
            for day in range(1, 11)
        ]

        finding = analyze_dragon_tiger(AshareMarketSignals("verified", dragon_tiger=[record]), prices, history)

        self.assertEqual(finding.details["reason_types"], ["turnover"])
        self.assertEqual(finding.details["seat_type_counts"], {"券商营业部": 1, "机构专用": 1})
        self.assertGreater(finding.details["buy_concentration"], 0.7)
        self.assertTrue(any("正收益观察占比" in item for item in finding.evidence))
        self.assertFalse(any("胜率" in item for item in finding.evidence))
        self.assertIn("dragon-tiger-history-001", finding.source_ids)

    def test_same_seat_on_both_rankings_is_not_double_counted(self) -> None:
        duplicated = [
            DragonTigerSeatRecord("2026-07-10", "涨停", "测试证券营业部", "buy", 80, 20, 60),
            DragonTigerSeatRecord("2026-07-10", "涨停", "测试证券营业部", "sell", 80, 20, 60),
        ]
        record = DragonTigerRecord("2026-07-10", "涨停", 60, None, source_id="dragon-tiger-001", seat_records=duplicated)

        finding = analyze_dragon_tiger(AshareMarketSignals("verified", dragon_tiger=[record]))

        self.assertEqual(finding.details["seat_type_counts"], {"券商营业部": 1})
        self.assertEqual(finding.details["buy_concentration"], 1.0)


if __name__ == "__main__":
    unittest.main()
