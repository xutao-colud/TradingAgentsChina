from __future__ import annotations

import unittest

from app.graph.workflow import build_default_workflow
from app.schemas.report import AgentFinding, SkillInsight
from app.skills.investment_committee import assess_investment_faction_committee


class InvestmentCommitteeTest(unittest.TestCase):
    def test_default_sample_prefers_trend_capacity_route(self) -> None:
        report = build_default_workflow().run("600519", "2026-07-10")
        committee = next(item for item in report.skill_insights if item.skill == "投资流派委员会")

        self.assertEqual(committee.category, "committee")
        self.assertEqual(committee.stage, "趋势容量派")
        self.assertIn("研讨问题", committee.evidence[0])
        self.assertIn("胜率代理排名", committee.evidence[1])
        self.assertIn("趋势容量派", committee.conclusion)
        self.assertEqual(committee.details["mode"], "court")
        self.assertEqual(committee.details["judge"]["winner"], "趋势容量派")
        self.assertIn("score_method", committee.details["judge"])
        self.assertGreaterEqual(len(committee.details["factions"]), 5)
        self.assertTrue(all("recommendation" in item for item in committee.details["factions"]))
        self.assertTrue(all("score_explanation" in item for item in committee.details["factions"]))
        self.assertTrue(all(item["score_adjustments"] for item in committee.details["factions"]))
        for faction in committee.details["factions"]:
            self.assertIn("score_basis", faction)
            self.assertIn("playbook_checks", faction)
            self.assertIn("core_logic", faction["playbook_checks"])
            self.assertTrue(faction["playbook_checks"]["must_confirm"])
            self.assertTrue(faction["playbook_checks"]["invalid_if"])
            for adjustment in faction["score_adjustments"]:
                self.assertIn("observed", adjustment)
                self.assertIn("threshold", adjustment)
                self.assertIn("source", adjustment)
                self.assertIn("direction", adjustment)

    def test_committee_responds_to_user_question(self) -> None:
        report = build_default_workflow().run(
            "000725.SZ",
            "2026-07-10",
            user_question="现在适合短线入手还是等回踩？",
        )
        committee = next(item for item in report.skill_insights if item.skill == "投资流派委员会")

        self.assertEqual(committee.details["judge"]["discussion_topic"], "现在适合短线入手还是等回踩？")
        self.assertEqual(committee.details["user_question"], "现在适合短线入手还是等回踩？")
        self.assertIn("现在适合短线入手还是等回踩？", committee.evidence[0])
        self.assertTrue(all(item["discussion_topic"] == "现在适合短线入手还是等回踩？" for item in committee.details["factions"]))
        self.assertTrue(any("围绕「现在适合短线入手还是等回踩？」" in item["question_response"] for item in committee.details["factions"]))
        self.assertIn("针对你的短线问题", committee.details["judge"]["action"])

    def test_defensive_route_wins_when_market_retreats_and_rules_block(self) -> None:
        findings = [
            AgentFinding("市场周期 Agent", "市场弱", 38, 0.6),
            AgentFinding("基本面 Agent", "一般", 55, 0.6),
            AgentFinding("技术分析 Agent", "破位", 35, 0.6),
            AgentFinding("资金流 Agent", "流出", 32, 0.6),
            AgentFinding("题材热点 Agent", "退潮", 40, 0.6),
        ]
        insights = [
            SkillInsight("A股市场温度计", "market", "防守", 35, "弱", "防守"),
            SkillInsight("情绪周期识别", "market", "退潮", 30, "退潮", "防守"),
            SkillInsight("赚钱效应分析", "market", "弱", 32, "弱", "防守"),
            SkillInsight("热点生命周期分析", "theme", "退潮", 35, "退潮", "防守"),
            SkillInsight("主力资金行为识别", "capital", "派发", 30, "派发", "防守"),
            SkillInsight("A股风险扫描器", "risk", "C级", 45, "风险高", "排除"),
        ]

        committee = assess_investment_faction_committee(findings, insights, ["ST 风险标识"])

        self.assertTrue(committee.stage.startswith("防守风控派"))
        self.assertIn("规则约束", " ".join(committee.evidence))
        self.assertIn("降低进攻优先级", committee.strategy)


if __name__ == "__main__":
    unittest.main()
