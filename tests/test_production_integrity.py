from __future__ import annotations

import unittest
from pathlib import Path

from app.data.providers.production_provider import ProductionMarketDataProvider
from app.graph.workflow import build_default_workflow
from app.mcp.server import McpToolServer


ROOT = Path(__file__).resolve().parents[1]


class ProductionIntegrityTest(unittest.TestCase):
    def test_all_implicit_entry_points_use_production_provider(self) -> None:
        self.assertIsInstance(build_default_workflow().provider, ProductionMarketDataProvider)
        self.assertIsInstance(McpToolServer().provider, ProductionMarketDataProvider)

    def test_legacy_business_threshold_literals_do_not_return(self) -> None:
        forbidden_by_file = {
            "app/skills/market_strategy_gate.py": ["temperature_score < 45", "temperature_score >= 55", "score = 75"],
            "app/skills/profile_alignment.py": ["technical.score >= 70", "score -= 25", "risk.score < 60"],
            "app/skills/stock_score_model.py": ["agent_score * 0.62", "skill_score * 0.38", "item.score < 60) * 8"],
            "app/playbooks/evaluator.py": ["score = 50", "score = min(score, 45)", "score >= 72"],
            "app/agents/portfolio_manager.py": ["weighted * 0.65", "composite.score * 0.35", "weighted >= 78"],
            "app/agents/risk_manager.py": ["finding.score < 45", "data_readiness.score < 70", "risk_score < 60"],
            "app/skills/investment_committee.py": [
                '_score_adjustment("情绪周期", 18',
                '_score_adjustment("题材阶段", 9',
                '_score_adjustment("趋势陷阱", -10',
                '_score_adjustment("风险扫描", 24',
                "限制到 0-100",
                "60 分以上支持短线进攻",
            ],
        }
        for relative_path, forbidden in forbidden_by_file.items():
            content = (ROOT / relative_path).read_text(encoding="utf-8")
            for literal in forbidden:
                self.assertNotIn(literal, content, f"business rule must come from runtime config: {relative_path}: {literal}")


if __name__ == "__main__":
    unittest.main()
