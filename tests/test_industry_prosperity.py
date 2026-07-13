from __future__ import annotations

import unittest

from app.schemas.report import (
    DataQualityReport,
    FundamentalSnapshot,
    IndustryChainNode,
    IndustryContext,
    IndustryFlowObservation,
    IndustryValuationObservation,
)
from app.skills.industry_prosperity import analyze_industry_prosperity


class IndustryProsperityTest(unittest.TestCase):
    def test_computes_flow_rank_valuation_growth_gap_and_chain_transmission(self) -> None:
        context = IndustryContext(
            data_status="verified",
            industry="中游",
            as_of="2026-07-10",
            flow_observations=[
                _flow("上游", 400_000_000, "A"),
                _flow("中游", 300_000_000, "B"),
                _flow("下游", 200_000_000, "C"),
                _flow("其他", -100_000_000, "D"),
            ],
            valuation_history=[
                IndustryValuationObservation(f"2026-0{index}-28", 10 + index, 1 + index * 0.1, 10, ["industry-valuation-001"])
                for index in range(1, 7)
            ],
            chain_nodes=[
                IndustryChainNode("upstream", "上游", "industry-chain-001"),
                IndustryChainNode("midstream", "中游", "industry-chain-001"),
                IndustryChainNode("downstream", "下游", "industry-chain-001"),
            ],
            source_ids=["industry-flow-001", "industry-valuation-001", "industry-chain-001"],
        )
        fundamentals = _fundamentals(
            revenue_growth=20,
            profit_growth=25,
            peer_revenue_growth=10,
            peer_profit_growth=12,
        )

        insight = analyze_industry_prosperity(context, fundamentals, _quality_reports())

        self.assertTrue(insight.details["admissible"])
        self.assertEqual(insight.details["flow"]["rank"], 2)
        self.assertEqual(insight.details["flow"]["total"], 4)
        self.assertEqual(insight.details["valuation"]["pe_percentile"], 100.0)
        self.assertEqual(insight.details["growth"]["profit_gap_pct"], 13)
        self.assertEqual(insight.details["chain"]["direction"], "positive")
        self.assertIn("peer-fund-001", insight.details["source_ids"])
        self.assertIn("行业资金流是观察性证据", " ".join(insight.risks))

    def test_mixed_chain_is_counter_evidence_not_positive_transmission(self) -> None:
        context = IndustryContext(
            "verified",
            "中游",
            "2026-07-10",
            flow_observations=[
                _flow("上游", 200_000_000, "A"),
                _flow("中游", 100_000_000, "B"),
                _flow("下游", -300_000_000, "C"),
            ],
            valuation_history=[
                IndustryValuationObservation(f"2026-0{index}-28", 15, 2, 10, ["industry-valuation-001"])
                for index in range(1, 7)
            ],
            chain_nodes=[
                IndustryChainNode("upstream", "上游", "industry-chain-001"),
                IndustryChainNode("midstream", "中游", "industry-chain-001"),
                IndustryChainNode("downstream", "下游", "industry-chain-001"),
            ],
            source_ids=["industry-flow-001", "industry-valuation-001", "industry-chain-001"],
        )

        insight = analyze_industry_prosperity(context, _fundamentals(10, 10, 10, 10), _quality_reports())

        self.assertEqual(insight.details["chain"]["direction"], "mixed")
        self.assertIn("上下游资金方向分化", " ".join(insight.details["counter_evidence"]))
        self.assertEqual(insight.details["score_components"]["chain"], 0.0)

    def test_rejects_missing_target_flow_or_failed_quality(self) -> None:
        context = IndustryContext(
            "partial",
            "未匹配行业",
            "2026-07-10",
            flow_observations=[_flow("其他", 10, "A")],
            source_ids=["industry-flow-001"],
            unavailable_reasons=["行业分类无法对齐"],
        )
        failed = DataQualityReport("tushare", "industry_flow", "failed", 1, 1, 1.0, "2026-07-10")

        insight = analyze_industry_prosperity(context, _fundamentals(10, 10, 10, 10), [failed])

        self.assertEqual(insight.stage, "证据不足")
        self.assertFalse(insight.details["admissible"])
        self.assertIn("暂停", insight.strategy)


def _flow(industry: str, net_amount: float, code: str) -> IndustryFlowObservation:
    return IndustryFlowObservation("2026-07-10", industry, code, net_amount, 1.0, 20, "industry-flow-001")


def _fundamentals(
    revenue_growth: float,
    profit_growth: float,
    peer_revenue_growth: float,
    peer_profit_growth: float,
) -> FundamentalSnapshot:
    return FundamentalSnapshot(
        revenue_growth,
        profit_growth,
        10,
        30,
        40,
        20,
        2,
        1,
        "稳定",
        peer_medians={
            "revenue_growth_yoy": peer_revenue_growth,
            "profit_growth_yoy": peer_profit_growth,
        },
        peer_sample_sizes={"revenue_growth_yoy": 10, "profit_growth_yoy": 10},
        peer_as_of="2026-03-31",
        peer_source_id="peer-fund-001",
    )


def _quality_reports() -> list[DataQualityReport]:
    return [
        DataQualityReport("tushare", "industry_flow", "passed", 4, 4, 1.0, "2026-07-10"),
        DataQualityReport("tushare", "industry_valuation", "passed", 6, 6, 1.0, "2026-07-10"),
    ]


if __name__ == "__main__":
    unittest.main()
