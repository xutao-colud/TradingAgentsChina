from __future__ import annotations

import unittest

from app.data.providers.akshare_provider import AkshareSupplementProvider
from app.data.providers.production_provider import ProductionMarketDataProvider
from app.data.providers.tushare_provider import TushareMarketDataProvider
from app.graph.workflow import AShareResearchWorkflow
from app.reporting.render import render_markdown
from test_akshare_provider import FakeAkshare
from test_tushare_provider import FakeTushare


class ProductionWorkflowTest(unittest.TestCase):
    def test_real_source_records_reach_agents_without_sample_relabelling(self) -> None:
        workflow = AShareResearchWorkflow(
            ProductionMarketDataProvider(TushareMarketDataProvider(FakeTushare()), AkshareSupplementProvider(FakeAkshare()))
        )

        report = workflow.run("600519", "2026-07-10")

        dragon_tiger = next(item for item in report.agent_findings if item.agent == "龙虎榜 Agent")
        announcement = next(item for item in report.agent_findings if item.agent == "新闻公告 Agent")
        self.assertEqual(dragon_tiger.source_ids, ["dragon-tiger-001"])
        self.assertTrue(any(source.source_type.startswith("tushare_") for source in report.evidence_sources))
        self.assertFalse(any(source.source_type == "offline_sample" for source in report.evidence_sources))
        self.assertTrue(any("限售解禁" in line for line in announcement.evidence))
        self.assertTrue(any(item.dataset == "dragon_tiger" for item in report.data_quality_reports))
        self.assertTrue(any(item.dataset.startswith("raw:") for item in report.data_quality_reports))
        committee = next(item for item in report.skill_insights if item.skill == "投资流派委员会")
        self.assertEqual(committee.details["signal_evidence"]["dragon_tiger"]["status"], "admitted")
        self.assertEqual(committee.details["signal_evidence"]["margin_financing"]["status"], "admitted")
        self.assertEqual(committee.details["signal_evidence"]["northbound_holding"]["status"], "admitted")
        markdown = render_markdown(report)
        self.assertIn("## 数据质量与原始快照", markdown)
        self.assertIn("tushare.raw:top_list", markdown)


if __name__ == "__main__":
    unittest.main()
