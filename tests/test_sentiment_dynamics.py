from __future__ import annotations

import unittest

from app.schemas.report import MarketContext, MarketSentimentObservation
from app.schemas.report import SkillInsight
from app.skills.market_strategy_gate import select_market_eligible_playbooks
from app.skills.sentiment_dynamics import analyze_sentiment_dynamics


def context_with(history: list[MarketSentimentObservation]) -> MarketContext:
    return MarketContext("上证", 0, 0, 0, 0, 0, 0, "未知", [], sentiment_history=history)


class SentimentDynamicsTest(unittest.TestCase):
    def test_recovery_and_retreat_are_detected_from_change_rate(self) -> None:
        recovery = analyze_sentiment_dynamics(context_with([
            MarketSentimentObservation("1", 5, 30, 45, -2, 1, 3, 10, -3),
            MarketSentimentObservation("2", 10, 25, 40, -1, 1, 8, 12, -2),
            MarketSentimentObservation("3", 40, 8, 18, 2, 4, 30, 35, 3),
        ]))
        retreat = analyze_sentiment_dynamics(context_with([
            MarketSentimentObservation("1", 70, 5, 15, 3, 5, 40, 40, 4),
            MarketSentimentObservation("2", 60, 10, 22, 2, 4, 32, 30, 2),
            MarketSentimentObservation("3", 15, 35, 48, -3, 1, 8, 8, -4),
        ]))

        self.assertIn(recovery.stage, {"启动", "发酵"})
        self.assertEqual(retreat.stage, "退潮")

    def test_single_observation_is_explicitly_insufficient(self) -> None:
        dynamics = analyze_sentiment_dynamics(context_with([MarketSentimentObservation("1", 30, 10, 20, 1, 3, 20, 20, 1)]))

        self.assertEqual(dynamics.stage, "数据不足")
        self.assertIsNotNone(dynamics.insufficient_reason)

    def test_market_gate_limits_research_to_defensive_route_without_sentiment_history(self) -> None:
        insight = select_market_eligible_playbooks([
            SkillInsight("A股市场温度计", "market", "震荡", 65, "", ""),
            SkillInsight("情绪周期识别", "market", "数据不足", 50, "", ""),
            SkillInsight("赚钱效应分析", "market", "一般", 65, "", ""),
        ])
        self.assertEqual(insight.stage, "情绪历史不足·防守研究")
        self.assertEqual(insight.details["allowed_playbooks"], ["institutional_value_dividend"])


if __name__ == "__main__":
    unittest.main()
