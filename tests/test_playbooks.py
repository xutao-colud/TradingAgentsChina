from __future__ import annotations

import unittest

from app.graph.workflow import build_default_workflow
from app.memory.models import TradingProfile
from app.playbooks.catalog import DEFAULT_PLAYBOOK_ID, list_playbooks
from app.playbooks.evaluator import assess_active_playbook
from app.schemas.report import AgentFinding, SkillInsight


class PlaybookTest(unittest.TestCase):
    def test_catalog_has_public_archetypes(self) -> None:
        ids = {item.id for item in list_playbooks()}
        self.assertEqual(DEFAULT_PLAYBOOK_ID, "trend_core")
        self.assertTrue({"hot_money_leader", "trend_core", "institutional_growth", "institutional_value_dividend"}.issubset(ids))

    def test_workflow_adds_active_playbook_assessment(self) -> None:
        profile = TradingProfile(active_playbook="institutional_growth")
        report = build_default_workflow().run("600519", "2026-07-10", profile)
        assessment = next(item for item in report.skill_insights if item.category == "playbook")
        self.assertEqual(report.active_playbook, "institutional_growth")
        self.assertEqual(assessment.skill, "公开风格原型适配")
        self.assertIn(assessment.stage, {"适配", "观察", "不适配"})

    def test_hot_money_playbook_rejects_retreating_sentiment(self) -> None:
        findings = [
            AgentFinding("技术分析 Agent", "趋势", 80, 0.8),
            AgentFinding("资金流 Agent", "流入", 80, 0.8),
        ]
        insights = [
            SkillInsight("情绪周期识别", "market", "退潮", 30, "退潮", "防守"),
            SkillInsight("赚钱效应分析", "market", "弱", 40, "弱", "防守"),
            SkillInsight("热点生命周期分析", "theme", "高潮", 50, "高潮", "防守"),
            SkillInsight("A股风险扫描器", "risk", "B级", 70, "可控", "复核"),
        ]
        assessment = assess_active_playbook(TradingProfile(active_playbook="hot_money_leader"), findings, insights)
        assert assessment is not None
        self.assertEqual(assessment.stage, "不适配")
