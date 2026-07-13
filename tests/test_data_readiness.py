from __future__ import annotations

import unittest

from app.schemas.report import DailyPrice, EvidenceSource
from app.skills.data_readiness import assess_data_readiness


def _prices(count: int, trade_date: str = "2026-07-10") -> list[DailyPrice]:
    return [DailyPrice(trade_date, 10, 11, 9, 10, 1_000_000, 20_000_000, 1.0) for _ in range(count)]


class DataReadinessTest(unittest.TestCase):
    def test_sample_sources_are_explicitly_non_production(self) -> None:
        sources = [
            EvidenceSource(source_id, source_id, "offline_sample", "2026-07-10")
            for source_id in ("price-001", "fund-001", "flow-001", "market-001")
        ]

        insight = assess_data_readiness(sources, "2026-07-10", _prices(120))

        self.assertEqual(insight.stage, "样例数据")
        self.assertEqual(insight.score, 40)
        self.assertIn("不得将该报告用于市场事实", insight.strategy)

    def test_unavailable_or_short_price_history_is_insufficient(self) -> None:
        sources = [
            EvidenceSource("price-001", "price", "unavailable", "2026-07-10"),
            EvidenceSource("fund-001", "fund", "vendor", "2026-07-10"),
            EvidenceSource("flow-001", "flow", "vendor", "2026-07-10"),
            EvidenceSource("market-001", "market", "vendor", "2026-07-10"),
        ]

        insight = assess_data_readiness(sources, "2026-07-10", _prices(2))

        self.assertEqual(insight.stage, "数据不足")
        self.assertIn("price-001", insight.details["unavailable_source_ids"])
        self.assertLess(insight.score, 50)

    def test_time_mismatch_is_not_treated_as_current_fact(self) -> None:
        sources = [
            EvidenceSource("price-001", "price", "vendor", "2026-07-09"),
            EvidenceSource("fund-001", "fund", "vendor", "2026-06-30"),
            EvidenceSource("flow-001", "flow", "vendor", "2026-07-10"),
            EvidenceSource("market-001", "market", "vendor", "2026-07-10"),
        ]

        insight = assess_data_readiness(sources, "2026-07-10", _prices(30))

        self.assertEqual(insight.stage, "数据不足")
        self.assertEqual(insight.details["time_mismatch_source_ids"], ["price-001"])


if __name__ == "__main__":
    unittest.main()
