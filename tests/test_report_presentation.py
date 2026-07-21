from __future__ import annotations

import unittest

from app.graph.workflow import build_sample_workflow
from app.reporting.evidence_brief import build_compact_model_payload
from app.reporting.presentation import public_report_payload


class ReportPresentationTest(unittest.TestCase):
    def test_public_report_uses_court_roles_without_changing_internal_ids(self) -> None:
        report = build_sample_workflow().run("600519", "2026-07-10")

        self.assertIn("资金流 Agent", {item.agent for item in report.agent_findings})

        payload = public_report_payload(report)
        public_roles = {item["agent"] for item in payload["agent_findings"]}
        self.assertIn("资金审验方", public_roles)
        self.assertIn("市场审势方", public_roles)
        self.assertNotIn("资金流 Agent", public_roles)

    def test_nested_committee_explanations_and_judge_are_presented_consistently(self) -> None:
        report = build_sample_workflow().run("600519", "2026-07-10")
        payload = public_report_payload(report)
        committee = next(item for item in payload["skill_insights"] if item["category"] == "committee")
        judge = committee["details"]["judge"]
        rendered = str(payload)

        self.assertEqual(judge["role_label"], "主审判官")
        self.assertNotIn("资金流 Agent", rendered)
        self.assertNotIn("技术分析 Agent", rendered)
        self.assertNotIn("Agent均分", rendered)
        self.assertNotIn("Judge 裁决", rendered)

    def test_model_payload_uses_the_same_public_roles(self) -> None:
        report = build_sample_workflow().run("600519", "2026-07-10")
        payload = build_compact_model_payload(report)
        roles = {item["agent"] for item in payload["findings"]}

        self.assertNotIn("资金流 Agent", roles)
        self.assertTrue(roles <= {
            "市场审势方", "基本面举证方", "趋势验证方", "资金审验方",
            "席位追踪方", "公告核验方", "题材质证方",
        })
