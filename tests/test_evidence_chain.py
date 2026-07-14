from __future__ import annotations

import unittest

from app.graph.workflow import build_sample_workflow
from app.schemas.report import AgentFinding, EvidenceSource
from app.skills.evidence_chain import assess_evidence_chain_quality


class EvidenceChainTest(unittest.TestCase):
    def test_default_workflow_has_complete_evidence_chain(self) -> None:
        report = build_sample_workflow().run("600519", "2026-07-10")
        insight = next(item for item in report.skill_insights if item.skill == "证据链完整性")

        self.assertEqual(insight.category, "quality")
        self.assertEqual(insight.stage, "完整")
        self.assertEqual(insight.score, 100)
        self.assertFalse(insight.risks)

    def test_missing_sources_and_counterpoints_are_penalized(self) -> None:
        findings = [
            AgentFinding(
                agent="技术分析 Agent",
                conclusion="趋势偏强",
                score=80,
                confidence=0.8,
                evidence=["MA20 上方"],
                source_ids=[],
            ),
            AgentFinding(
                agent="资金流 Agent",
                conclusion="资金流入",
                score=70,
                confidence=0.7,
                evidence=[],
                counterpoints=["单日资金不可外推"],
                source_ids=["flow-404"],
            ),
        ]
        sources = [EvidenceSource("price-001", "样例价格", "sample", "2026-07-10")]

        insight = assess_evidence_chain_quality(findings, sources)

        self.assertLess(insight.score, 70)
        self.assertIn(insight.stage, {"待补证据", "不足"})
        self.assertTrue(any("缺少 source_ids" in item for item in insight.risks))
        self.assertTrue(any("未知来源" in item for item in insight.risks))

    def test_missing_invalidation_conditions_are_not_replayable(self) -> None:
        finding = AgentFinding(
            agent="测试 Agent",
            conclusion="测试结论",
            score=60,
            confidence=0.6,
            evidence=["已计算指标"],
            risks=["数据可能过期"],
            counterpoints=["需要更多来源确认"],
            source_ids=["source-001"],
        )
        source = EvidenceSource("source-001", "测试来源", "test", "2026-07-13")

        insight = assess_evidence_chain_quality([finding], [source])

        self.assertLess(insight.score, 90)
        self.assertTrue(any("失效条件" in item for item in insight.risks))


if __name__ == "__main__":
    unittest.main()
