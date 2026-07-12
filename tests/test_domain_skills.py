import unittest

from app.data.providers.sample_provider import SampleMarketDataProvider
from app.rules.trading_rules import normalize_symbol
from app.skills.market_temperature import assess_market_temperature
from app.skills.risk_scanner import scan_a_share_risks
from app.skills.sentiment_cycle import identify_sentiment_cycle
from app.skills.theme_lifecycle import analyze_theme_lifecycle


class DomainSkillsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = SampleMarketDataProvider()
        self.symbol = normalize_symbol("600519")
        self.context = self.provider.get_market_context("2026-07-10")
        self.profile = self.provider.get_stock_profile(self.symbol)

    def test_market_temperature_outputs_a_share_strategy(self) -> None:
        insight = assess_market_temperature(self.context)
        self.assertEqual(insight.skill, "A股市场温度计")
        self.assertGreaterEqual(insight.score, 0)
        self.assertLessEqual(insight.score, 100)
        self.assertTrue(insight.evidence)
        self.assertIn(insight.stage, {"防守", "震荡", "震荡修复", "进攻"})

    def test_sentiment_cycle_uses_limit_up_and_breakout_data(self) -> None:
        insight = identify_sentiment_cycle(self.context)
        self.assertEqual(insight.skill, "情绪周期识别")
        self.assertIn(insight.stage, {"冰点", "启动", "发酵", "高潮", "退潮"})
        self.assertTrue(any("炸板率" in item for item in insight.evidence))

    def test_theme_lifecycle_links_policy_theme_to_stock_profile(self) -> None:
        insight = analyze_theme_lifecycle(self.profile, self.context)
        self.assertEqual(insight.skill, "热点生命周期分析")
        self.assertGreaterEqual(insight.score, 50)
        self.assertTrue(any("消费复苏" in item for item in insight.evidence))

    def test_risk_scanner_explains_grade_and_check_principles(self) -> None:
        fundamentals = self.provider.get_fundamentals("000725.SZ")
        insight = scan_a_share_risks(self.provider.get_stock_profile("000725.SZ"), fundamentals, [])

        self.assertEqual(insight.skill, "A股风险扫描器")
        self.assertEqual(insight.details["mode"], "risk_scan")
        self.assertIn("grade_explanation", insight.details)
        self.assertGreaterEqual(len(insight.details["grade_guide"]), 4)
        self.assertTrue(any(item["name"] == "现金流质量" for item in insight.details["checks"]))
        self.assertTrue(insight.details["next_checks"])


if __name__ == "__main__":
    unittest.main()
