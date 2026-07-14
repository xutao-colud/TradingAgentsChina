from __future__ import annotations

import unittest

from app.agents.risk_manager import assess_risk
from app.schemas.report import AgentFinding, SkillInsight
from app.skills.stock_score_model import score_stock_composite


class ReasoningGuardTest(unittest.TestCase):
    def test_generic_caveats_do_not_make_every_report_high_risk(self) -> None:
        findings = [
            AgentFinding("技术分析 Agent", "趋势正常", 70, 0.7, risks=["指标存在滞后性"]),
            AgentFinding("资金流 Agent", "资金正常", 70, 0.7, risks=["单日资金存在噪声"]),
        ]
        risk = SkillInsight("A股风险扫描器", "risk", "A级", 82, "风险可控", "继续核验")

        level, risks = assess_risk(findings, [], [risk])

        self.assertEqual(level, "低")
        self.assertEqual(len(risks), 2)

    def test_composite_excludes_governance_scores(self) -> None:
        findings = [AgentFinding("技术分析 Agent", "趋势正常", 60, 0.6)]
        signals = [SkillInsight("市场", "market", "震荡", 50, "", "")]
        governance = [
            SkillInsight("数据就绪性审查", "data_quality", "已核验", 100, "", ""),
            SkillInsight("委员会", "committee", "", 100, "", ""),
            SkillInsight("画像", "personalization", "", 0, "", ""),
        ]

        signal_only = score_stock_composite(findings, signals)
        with_governance = score_stock_composite(findings, signals + governance)

        self.assertEqual(signal_only.score, with_governance.score)


if __name__ == "__main__":
    unittest.main()
