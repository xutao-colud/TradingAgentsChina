from __future__ import annotations

import json
import unittest
from dataclasses import replace

from app.graph.workflow import build_sample_workflow
from app.reporting.evidence_brief import build_compact_model_payload, build_decision_brief
from app.reporting.render import render_markdown
from app.schemas.report import AgentFinding


class EvidenceBriefTest(unittest.TestCase):
    def test_workflow_builds_traceable_decision_brief_without_model(self) -> None:
        report = build_sample_workflow().run("600519", "2026-07-10")
        brief = report.decision_brief

        self.assertEqual(brief["version"], "evidence-brief-v1")
        self.assertTrue(brief["decisive_evidence"])
        self.assertIn(brief["court"]["status"], {"decided", "refused"})
        for claim in brief["decisive_evidence"]:
            self.assertTrue(claim["sources"])
            self.assertTrue(all(source["id"] and source["as_of"] for source in claim["sources"]))

    def test_untraceable_finding_cannot_enter_decisive_evidence(self) -> None:
        report = build_sample_workflow().run("600519", "2026-07-10")
        untraceable = AgentFinding(
            agent="无来源观点",
            conclusion="不可进入核心证据",
            score=100,
            confidence=1.0,
            evidence=["没有来源的强观点"],
            source_ids=["missing-source"],
        )
        modified = replace(report, agent_findings=[untraceable], evidence_sources=[], decision_brief={})

        brief = build_decision_brief(modified)

        self.assertEqual(brief["decisive_evidence"], [])
        self.assertEqual(brief["data_boundary"]["traceable_finding_count"], 0)

    def test_model_payload_is_compact_and_omits_raw_quality_log(self) -> None:
        report = build_sample_workflow().run("600519", "2026-07-10")

        compact = build_compact_model_payload(report)
        compact_json = json.dumps(compact, ensure_ascii=False)
        full_json = json.dumps(report.to_dict(), ensure_ascii=False)

        self.assertIn("decision_brief", compact)
        self.assertNotIn("data_quality_reports", compact)
        self.assertNotIn("skill_insights", compact)
        self.assertLess(len(compact_json), len(full_json))

    def test_markdown_places_evidence_brief_before_scores(self) -> None:
        report = build_sample_workflow().run("600519", "2026-07-10")
        markdown = render_markdown(report)

        self.assertLess(markdown.index("## 证据裁决简报"), markdown.index("## 核心评分"))
        self.assertIn("### 决定性证据", markdown)
        self.assertIn("### 最强反证与失效条件", markdown)


if __name__ == "__main__":
    unittest.main()
