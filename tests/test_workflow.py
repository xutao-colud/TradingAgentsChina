import json
import unittest

from app.graph.workflow import build_default_workflow
from app.memory.models import TradingProfile
from app.schemas.report import DailyPrice, StockProfile
from app.data.providers.sample_provider import SampleMarketDataProvider


class WorkflowTest(unittest.TestCase):
    def test_workflow_builds_traceable_report(self) -> None:
        report = build_default_workflow().run("600519", "2026-07-10")
        self.assertEqual(report.symbol, "600519.SH")
        self.assertEqual(report.name, "贵州茅台")
        self.assertGreaterEqual(report.fundamental_score, 0)
        self.assertLessEqual(report.fundamental_score, 100)
        self.assertGreater(len(report.agent_findings), 4)
        self.assertGreaterEqual(len(report.skill_insights), 8)
        self.assertGreater(len(report.evidence_sources), 3)
        self.assertIn(report.conclusion, {"强烈关注", "谨慎关注", "中性观察", "风险较高", "暂不参与"})

    def test_sample_provider_resolves_known_a_share_names(self) -> None:
        report = build_default_workflow().run("000725.SZ", "2026-07-10")
        self.assertEqual(report.symbol, "000725.SZ")
        self.assertEqual(report.name, "京东方A")
        theme = next(item for item in report.agent_findings if item.agent == "题材热点 Agent")
        self.assertFalse(any("消费复苏" in item and "匹配主题" in item for item in theme.evidence))
        evidence_quality = next(item for item in report.skill_insights if item.skill == "证据链完整性")
        self.assertEqual(evidence_quality.score, 100)

    def test_report_is_json_serializable(self) -> None:
        report = build_default_workflow().run("600519", "2026-07-10", user_question="是否适合我的趋势回踩打法？")
        encoded = json.dumps(report.to_dict(), ensure_ascii=False)
        self.assertIn("贵州茅台", encoded)
        self.assertIn("是否适合我的趋势回踩打法？", encoded)
        self.assertIn("agent_findings", encoded)
        self.assertIn("skill_insights", encoded)
        self.assertIn("情绪周期识别", encoded)

    def test_invalid_conditions_lower_committee_rating(self) -> None:
        class RiskyProvider(SampleMarketDataProvider):
            def get_stock_profile(self, symbol: str) -> StockProfile:
                return StockProfile(symbol=symbol, name="ST样例", industry="样例", board="main", is_st=True)

            def get_daily_prices(self, symbol: str, analysis_date: str, lookback_days: int) -> list[DailyPrice]:
                prices = super().get_daily_prices(symbol, analysis_date, lookback_days)
                latest = prices[-1]
                prices[-1] = DailyPrice(
                    latest.trade_date,
                    latest.open,
                    latest.high,
                    latest.low,
                    latest.close,
                    latest.volume,
                    10_000_000,
                    0.1,
                )
                return prices

        from app.graph.workflow import AShareResearchWorkflow

        report = AShareResearchWorkflow(RiskyProvider()).run("600000", "2026-07-10")
        self.assertTrue(report.invalid_conditions)
        self.assertIn(report.risk_level, {"中", "高"})
        self.assertNotEqual(report.conclusion, "强烈关注")


    def test_profile_alignment_is_included_when_profile_is_supplied(self) -> None:
        report = build_default_workflow().run(
            "600519",
            "2026-07-10",
            trading_profile=TradingProfile(),
        )
        alignment = next(item for item in report.skill_insights if item.category == "personalization")
        self.assertEqual(alignment.skill, "个人交易画像适配")


if __name__ == "__main__":
    unittest.main()
