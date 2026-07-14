from __future__ import annotations

import unittest

from app.rules.risk_facts import enrich_stock_profile_risks
from app.schemas.report import (
    Announcement,
    AshareMarketSignals,
    CorporateEvent,
    DailyPrice,
    DataQualityReport,
    EvidenceSource,
    FundamentalSnapshot,
    StockProfile,
)
from app.skills.risk_scanner import scan_a_share_risks


def _fundamentals(**overrides: object) -> FundamentalSnapshot:
    values: dict[str, object] = {
        "revenue_growth_yoy": 10,
        "profit_growth_yoy": 12,
        "roe": 10,
        "gross_margin": 30,
        "debt_to_asset": 30,
        "pe_ttm": 20,
        "pb": 2,
        "cashflow_quality": 1.2,
        "forecast_revision": "无",
        "statement_as_of": "2026-03-31",
    }
    values.update(overrides)
    return FundamentalSnapshot(**values)  # type: ignore[arg-type]


class AShareRiskScannerTest(unittest.TestCase):
    def test_profile_enrichment_keeps_triggered_events_traceable(self) -> None:
        reduction = CorporateEvent(
            "股东增减持", "重要股东减持", "2026-07-01", "negative", "减持披露", "reduction-1"
        )
        inquiry = Announcement(
            "年度报告问询函", "2026-06-20", "exchange", "negative", "问询", "inquiry-1", event_type="inquiry"
        )
        profile = enrich_stock_profile_risks(
            StockProfile("600519.SH", "测试", "电子", "main"),
            AshareMarketSignals("verified", corporate_events=[reduction]),
            [inquiry],
            [
                EvidenceSource("reduction-1", "减持", "tushare_stk_holdertrade", "2026-07-01"),
                EvidenceSource("inquiry-1", "问询", "cninfo", "2026-06-20"),
            ],
            [],
            "2026-07-10",
        )

        self.assertTrue(profile.major_shareholder_reduction)
        self.assertEqual(profile.major_shareholder_reduction_count, 1)
        self.assertEqual(profile.major_shareholder_reduction_source_ids, ["reduction-1"])
        self.assertEqual(profile.inquiry_count, 1)
        self.assertEqual(profile.inquiry_source_ids, ["inquiry-1"])

    def test_profile_enrichment_only_marks_no_event_when_coverage_passes(self) -> None:
        sources = [
            EvidenceSource("holder-trade-coverage-tushare-001", "覆盖", "tushare", "2026-07-10"),
            EvidenceSource("announcement-coverage-cninfo-001", "覆盖", "cninfo", "2026-07-10"),
        ]
        quality = [
            DataQualityReport("tushare", "holder_trades", "passed", 0, 0, 0, as_of="2026-07-10"),
            DataQualityReport("akshare", "announcements", "passed", 1, 1, 1, as_of="2026-07-10"),
        ]
        profile = enrich_stock_profile_risks(
            StockProfile("600519.SH", "测试", "电子", "main"),
            AshareMarketSignals("verified"),
            [],
            sources,
            quality,
            "2026-07-10",
        )

        self.assertFalse(profile.major_shareholder_reduction)
        self.assertEqual(profile.major_shareholder_reduction_count, 0)
        self.assertEqual(profile.inquiry_count, 0)

    def test_new_risks_use_configured_deductions_and_do_not_double_count_liquidity(self) -> None:
        profile = StockProfile(
            "600519.SH", "测试", "电子", "main",
            major_shareholder_reduction=True,
            major_shareholder_reduction_count=1,
            major_shareholder_reduction_as_of="2026-07-01",
            major_shareholder_reduction_source_ids=["reduction-1"],
            inquiry_count=2,
            inquiry_as_of="2026-06-20",
            inquiry_source_ids=["inquiry-1", "inquiry-2"],
        )
        fundamentals = _fundamentals(
            goodwill_ratio=30,
            goodwill_as_of="2026-03-31",
            goodwill_source_id="fund-001",
            pledge_ratio=40,
            pledge_as_of="2026-07-04",
            pledge_source_id="pledge-risk-001",
        )
        prices = [
            DailyPrice(f"2026-07-0{index}", 10, 10, 10, 10, 100, 1_000_000, 0.1)
            for index in range(1, 6)
        ]
        insight = scan_a_share_risks(
            profile,
            fundamentals,
            ["最新成交额低于配置阈值"],
            prices=prices,
            evidence_sources=[
                EvidenceSource("fund-001", "财报", "tushare", "2026-03-31"),
                EvidenceSource("pledge-risk-001", "质押", "tushare", "2026-07-04"),
                EvidenceSource("price-001", "日线", "tushare", "2026-07-05"),
            ],
        )

        deductions = {item["item"]: item["points"] for item in insight.details["deductions"]}
        self.assertEqual(insight.details["total_deduction"], 66)
        self.assertEqual(insight.score, 16)
        self.assertEqual(deductions["重要股东减持"], 12)
        self.assertEqual(deductions["交易所问询"], 10)
        self.assertEqual(deductions["商誉占净资产"], 12)
        self.assertEqual(deductions["股权质押比例"], 14)
        self.assertNotIn("交易规则/可执行性", deductions)
        self.assertTrue(all("source_ids" in item and "invalidation_condition" in item for item in insight.details["checks"]))

    def test_missing_new_risk_data_is_not_treated_as_safe_or_deducted(self) -> None:
        insight = scan_a_share_risks(
            StockProfile("600519.SH", "测试", "电子", "main"),
            _fundamentals(),
            [],
        )

        self.assertEqual(insight.score, 82)
        for name in ("重要股东减持", "交易所问询", "商誉占净资产", "股权质押比例", "日均成交额", "平均换手率"):
            self.assertIn(name, insight.details["insufficient_checks"])


if __name__ == "__main__":
    unittest.main()
