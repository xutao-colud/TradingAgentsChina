from __future__ import annotations

from dataclasses import replace
import unittest

from app.graph.workflow import build_default_workflow
from app.schemas.report import (
    AgentFinding,
    AshareMarketSignals,
    DataQualityReport,
    DragonTigerRecord,
    EvidenceSource,
    IntradaySnapshot,
    MarginFinancingRecord,
    MoneyFlowSnapshot,
    NorthboundHoldingRecord,
    SkillInsight,
)
from app.skills.investment_committee import assess_investment_faction_committee


class InvestmentCommitteeTest(unittest.TestCase):
    def test_default_sample_prefers_trend_capacity_route(self) -> None:
        report = build_default_workflow().run("600519", "2026-07-10")
        committee = next(item for item in report.skill_insights if item.skill == "投资流派委员会")

        self.assertEqual(committee.category, "committee")
        self.assertEqual(committee.stage, "证据不足")
        self.assertTrue(any("数据状态" in item for item in committee.evidence))
        self.assertIn("拒绝裁决", committee.conclusion)
        self.assertEqual(committee.details["mode"], "court")
        self.assertFalse(committee.details["factions"])
        self.assertFalse(committee.details["cross_examination"])
        self.assertEqual(committee.details["risk_challenge"]["role"], "risk_challenge")

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
        self.assertFalse(committee.details["factions"])
        self.assertIn("补齐数据", committee.details["judge"]["action"])

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

    def test_new_signals_are_routed_to_relevant_factions_with_traceability(self) -> None:
        findings, insights = _committee_baseline()
        committee = assess_investment_faction_committee(
            findings,
            insights,
            [],
            analysis_date="2026-07-10",
            market_signals=_market_signals(positive=True),
            money_flow=_money_flow(positive=True),
            intraday=IntradaySnapshot(
                "verified",
                "2026-07-10 14:55:00",
                source_ids=["intraday-bars-001", "order-book-001"],
            ),
            evidence_sources=_evidence_sources(),
            quality_reports=_quality_reports(),
        )

        signals = committee.details["signal_evidence"]
        expected = {
            "dragon_tiger",
            "dragon_tiger_history",
            "margin_financing",
            "northbound_holding",
            "tiered_money_flow",
            "capital_flow_continuity",
            "intraday",
        }
        self.assertTrue(all(signals[name]["status"] == "admitted" for name in expected))
        aggressive = next(item for item in committee.details["factions"] if item["name"] == "激进游资派")
        trend = next(item for item in committee.details["factions"] if item["name"] == "趋势容量派")
        institutional = next(item for item in committee.details["factions"] if item["name"] == "机构成长派")
        aggressive_items = {item["item"]: item for item in aggressive["score_adjustments"]}
        trend_items = {item["item"]: item for item in trend["score_adjustments"]}
        institutional_items = {item["item"]: item for item in institutional["score_adjustments"]}
        self.assertIn("龙虎榜净额", aggressive_items)
        self.assertIn("盘口委托不平衡", aggressive_items)
        self.assertIn("北向持股变化", institutional_items)
        self.assertIn("融资融券活动", institutional_items)
        self.assertIn("龙虎榜席位类型", aggressive_items)
        self.assertIn("龙虎榜游资席位历史后效", aggressive_items)
        self.assertIn("主力资金连续性", aggressive_items)
        self.assertIn("融资余额趋势", trend_items)
        self.assertIn("北向资金连续性", institutional_items)
        self.assertIn("行业景气度", institutional_items)
        self.assertEqual(institutional_items["行业景气度"]["evidence_status"], "admitted")
        self.assertEqual(aggressive_items["龙虎榜净额"]["source_ids"], ["dragon-tiger-001"])
        self.assertEqual(aggressive_items["龙虎榜净额"]["as_of"], "2026-07-10")
        self.assertEqual(aggressive_items["龙虎榜净额"]["evidence_status"], "admitted")
        self.assertEqual(committee.details["decision_context"]["northbound_days"], 5)
        self.assertEqual(committee.details["decision_context"]["margin_trend"], 4)
        self.assertEqual(
            committee.details["decision_context"]["dragon_tiger_signal"]["status"],
            "admitted",
        )
        self.assertIn("正收益观察占比", signals["dragon_tiger_history"]["observed"])
        self.assertNotIn("胜率", signals["dragon_tiger_history"]["observed"])

    def test_continuity_components_only_move_their_intended_factions(self) -> None:
        findings, insights = _committee_baseline()
        common = {
            "analysis_date": "2026-07-10",
            "market_signals": _market_signals(positive=True),
            "money_flow": _money_flow(positive=True),
            "intraday": IntradaySnapshot(
                "verified", "2026-07-10 14:55:00",
                source_ids=["intraday-bars-001", "order-book-001"],
            ),
            "evidence_sources": _evidence_sources(),
            "quality_reports": _quality_reports(),
        }
        north_positive = assess_investment_faction_committee(
            findings, _with_continuity(insights, main=2, northbound=5, margin=0), [], **common,
        )
        north_negative = assess_investment_faction_committee(
            findings, _with_continuity(insights, main=2, northbound=-5, margin=0), [], **common,
        )
        self.assertGreater(
            _faction_score(north_positive, "机构成长派"),
            _faction_score(north_negative, "机构成长派"),
        )
        self.assertEqual(
            _faction_score(north_positive, "激进游资派"),
            _faction_score(north_negative, "激进游资派"),
        )
        self.assertEqual(
            _faction_score(north_positive, "趋势容量派"),
            _faction_score(north_negative, "趋势容量派"),
        )

        margin_positive = assess_investment_faction_committee(
            findings, _with_continuity(insights, main=2, northbound=0, margin=5), [], **common,
        )
        margin_negative = assess_investment_faction_committee(
            findings, _with_continuity(insights, main=2, northbound=0, margin=-5), [], **common,
        )
        self.assertGreater(
            _faction_score(margin_positive, "趋势容量派"),
            _faction_score(margin_negative, "趋势容量派"),
        )
        self.assertEqual(
            _faction_score(margin_positive, "激进游资派"),
            _faction_score(margin_negative, "激进游资派"),
        )
        self.assertEqual(
            _faction_score(margin_positive, "机构成长派"),
            _faction_score(margin_negative, "机构成长派"),
        )

    def test_a_share_characteristic_signals_enter_relevant_court_routes(self) -> None:
        findings, insights = _committee_baseline()
        insights.extend([
            SkillInsight(
                "A股涨停结构", "market", "封板强", 72, "封板结构已核验", "仅作情绪证据",
                details={"admitted": True, "sealed_limit_up_rate": 82.0, "failed_breakout_rate": 18.0, "source_ids": ["market-001"], "as_of": "2026-07-10"},
            ),
            SkillInsight(
                "换手率连续变化", "capital", "持续放大", 68, "换手连续放大", "与趋势交叉验证",
                details={"admitted": True, "latest_turnover_rate": 5.0, "5d_change_pct": 25.0, "source_ids": ["price-001"], "as_of": "2026-07-10"},
            ),
            SkillInsight(
                "AH股溢价观察", "valuation", "A股高溢价", 45, "A股溢价 20%", "只作相对估值",
                details={"admitted": True, "premium_pct": 20.0, "source_ids": ["ah-premium-001"], "as_of": "2026-07-10"},
            ),
        ])
        evidence = [
            *_evidence_sources(),
            EvidenceSource("market-001", "涨停与炸板池", "tushare_limit_list_d", "2026-07-10"),
            EvidenceSource("price-001", "日线与换手率", "tushare_daily_basic", "2026-07-10"),
            EvidenceSource("ah-premium-001", "AH股比价", "tushare_stk_ah_comparison", "2026-07-10"),
        ]
        quality = [
            *_quality_reports(),
            DataQualityReport("tushare", "market_sentiment", "passed", 5, 5, 1.0, "2026-07-10"),
            DataQualityReport("tushare", "daily_prices", "passed", 120, 120, 1.0, "2026-07-10"),
            DataQualityReport("tushare", "ah_premium", "passed", 1, 1, 1.0, "2026-07-10"),
        ]

        committee = assess_investment_faction_committee(
            findings,
            insights,
            [],
            analysis_date="2026-07-10",
            market_signals=_market_signals(positive=True),
            money_flow=_money_flow(positive=True),
            intraday=IntradaySnapshot("verified", "2026-07-10 14:55:00", source_ids=["intraday-bars-001", "order-book-001"]),
            evidence_sources=evidence,
            quality_reports=quality,
        )

        signals = committee.details["signal_evidence"]
        self.assertEqual(signals["a_share_characteristics"]["status"], "admitted")
        self.assertEqual(signals["turnover_continuity"]["status"], "admitted")
        self.assertEqual(signals["ah_premium"]["status"], "admitted")
        adjustment_items = {
            item["item"]
            for faction in committee.details["factions"]
            for item in faction["score_adjustments"]
        }
        self.assertIn("涨停结构", adjustment_items)
        self.assertIn("换手连续性", adjustment_items)
        self.assertIn("AH股相对估值", adjustment_items)

    def test_negative_signals_reduce_aggressive_and_institutional_fit(self) -> None:
        findings, positive_insights = _committee_baseline(positive=True)
        _, negative_insights = _committee_baseline(positive=False)
        positive = assess_investment_faction_committee(
            findings,
            positive_insights,
            [],
            analysis_date="2026-07-10",
            market_signals=_market_signals(positive=True),
            money_flow=_money_flow(positive=True),
            intraday=IntradaySnapshot("verified", "2026-07-10 14:55:00", source_ids=["intraday-bars-001", "order-book-001"]),
            evidence_sources=_evidence_sources(),
            quality_reports=_quality_reports(),
        )
        negative = assess_investment_faction_committee(
            findings,
            negative_insights,
            [],
            analysis_date="2026-07-10",
            market_signals=_market_signals(positive=False),
            money_flow=_money_flow(positive=False),
            intraday=IntradaySnapshot("verified", "2026-07-10 14:55:00", source_ids=["intraday-bars-001", "order-book-001"]),
            evidence_sources=_evidence_sources(),
            quality_reports=_quality_reports(),
        )

        self.assertGreater(_faction_score(positive, "激进游资派"), _faction_score(negative, "激进游资派"))
        self.assertGreater(_faction_score(positive, "机构成长派"), _faction_score(negative, "机构成长派"))

    def test_failed_quality_and_stale_sources_are_rejected_without_score_impact(self) -> None:
        findings, insights = _committee_baseline()
        signals = _market_signals(positive=True)
        signals = AshareMarketSignals(
            signals.data_status,
            dragon_tiger=signals.dragon_tiger,
            margin_financing=signals.margin_financing,
            northbound_holding=NorthboundHoldingRecord("2026-07-09", 1000, 10000, 100, "northbound-001"),
        )
        quality = _quality_reports()
        quality[0] = DataQualityReport("tushare", "dragon_tiger", "failed", 1, 0, 0.0, "2026-07-10", blocking=False)
        committee = assess_investment_faction_committee(
            findings,
            insights,
            [],
            analysis_date="2026-07-10",
            market_signals=signals,
            money_flow=_money_flow(positive=True),
            intraday=IntradaySnapshot("verified", "2026-07-10 14:55:00", source_ids=["intraday-bars-001", "order-book-001"]),
            evidence_sources=_evidence_sources(),
            quality_reports=quality,
        )

        self.assertEqual(committee.details["signal_evidence"]["dragon_tiger"]["status"], "rejected")
        self.assertEqual(committee.details["signal_evidence"]["northbound_holding"]["status"], "rejected")
        aggressive = next(item for item in committee.details["factions"] if item["name"] == "激进游资派")
        institutional = next(item for item in committee.details["factions"] if item["name"] == "机构成长派")
        self.assertNotIn("龙虎榜净额", {item["item"] for item in aggressive["score_adjustments"]})
        self.assertNotIn("北向持股变化", {item["item"] for item in institutional["score_adjustments"]})


def _committee_baseline(positive: bool = True) -> tuple[list[AgentFinding], list[SkillInsight]]:
    findings = [
        AgentFinding("市场周期 Agent", "稳定", 60, 0.7),
        AgentFinding("基本面 Agent", "良好", 68, 0.7),
        AgentFinding("技术分析 Agent", "趋势", 62, 0.7),
        AgentFinding("资金流 Agent", "承接", 60, 0.7),
        AgentFinding("题材热点 Agent", "扩散", 60, 0.7),
        AgentFinding(
            "龙虎榜 Agent", "席位结构已核验", 60, 0.7,
            source_ids=["dragon-tiger-001", "dragon-tiger-history-001"],
            details={
                "buy_concentration": 0.4,
                "sell_concentration": 0.3,
                "seat_type_counts": {"游资席位": 1, "机构专用": 1},
                "known_hot_money_seat_count": 1,
                "seat_history_metrics": {
                    "配置游资席位": {
                        "seat_type": "游资席位",
                        "horizons": {
                            "3": {
                                "observations": 4,
                                "median_return_pct": 2.0,
                                "positive_observation_ratio": 0.75,
                            }
                        },
                    }
                },
            },
        ),
    ]
    tier_score = 70 if positive else 30
    imbalance = 0.2 if positive else -0.2
    insights = [
        SkillInsight("A股市场温度计", "market", "震荡修复", 60, "", ""),
        SkillInsight("情绪周期识别", "market", "启动", 60, "", ""),
        SkillInsight("赚钱效应分析", "market", "良好", 62, "", ""),
        SkillInsight("热点生命周期分析", "theme", "扩散", 65, "", ""),
        SkillInsight("主力资金行为识别", "capital", "吸筹", 62, "", ""),
        SkillInsight("资金流分档分析", "capital", "各档共同净流入" if positive else "各档共同净流出", tier_score, "", "", details={"large_side_net": 1 if positive else -1, "small_side_net": 1 if positive else -1}),
        SkillInsight(
            "资金流连续性分析",
            "capital",
            "主力连续净流入" if positive else "主力连续净流出",
            tier_score,
            "连续资金方向已形成",
            "仅作趋势验证",
            risks=["历史口径限制"],
            details={
                "main_streak_days": 5 if positive else -5,
                "northbound_streak_days": 5 if positive else -5,
                "margin_balance_streak_days": 4 if positive else -4,
                "source_ids": ["flow-history-001", "margin-history-001", "northbound-history-001"],
                "as_of": "2026-07-10",
            },
        ),
        SkillInsight("盘中分时盘口分析", "intraday", "买方承接偏强" if positive else "卖方压力偏强", 65 if positive else 35, "", "", details={"order_book_imbalance": imbalance}),
        SkillInsight(
            "行业景气度分析",
            "industry",
            "景气证据偏强" if positive else "景气证据偏弱",
            72 if positive else 32,
            "行业证据已核验",
            "仅作流派适配",
            details={
                "admissible": True,
                "as_of": "2026-07-10",
                "source_ids": ["industry-flow-001", "industry-valuation-001", "peer-fund-001"],
            },
        ),
        SkillInsight("A股风险扫描器", "risk", "B级", 70, "", ""),
    ]
    return findings, insights


def _market_signals(positive: bool) -> AshareMarketSignals:
    direction = 1 if positive else -1
    return AshareMarketSignals(
        "verified",
        dragon_tiger=[DragonTigerRecord("2026-07-10", "测试披露", 10_000_000 * direction, 5_000_000 * direction, source_id="dragon-tiger-001")],
        margin_financing=MarginFinancingRecord("2026-07-10", 100_000_000, 1_000_000, 5_000_000, 4_000_000, "margin-001"),
        northbound_holding=NorthboundHoldingRecord("2026-07-10", 1000, 10000, 100 * direction, "northbound-001"),
    )


def _with_continuity(
    insights: list[SkillInsight],
    *,
    main: int,
    northbound: int,
    margin: int,
) -> list[SkillInsight]:
    updated: list[SkillInsight] = []
    for insight in insights:
        if insight.skill != "资金流连续性分析":
            updated.append(insight)
            continue
        details = dict(insight.details)
        details.update({
            "main_streak_days": main,
            "northbound_streak_days": northbound,
            "margin_balance_streak_days": margin,
        })
        updated.append(replace(insight, details=details))
    return updated


def _money_flow(positive: bool) -> MoneyFlowSnapshot:
    direction = 1 if positive else -1
    return MoneyFlowSnapshot(
        10_000_000 * direction,
        5_000_000 * direction,
        0.8 * direction,
        "北向持股增加" if positive else "北向持股减少",
        2.0,
        "无异常",
        large_net_inflow=4_000_000 * direction,
        medium_net_inflow=2_000_000 * direction,
        small_net_inflow=1_000_000 * direction,
        as_of="2026-07-10",
    )


def _evidence_sources() -> list[EvidenceSource]:
    return [
        EvidenceSource("dragon-tiger-001", "龙虎榜", "tushare_top_list", "2026-07-10"),
        EvidenceSource("dragon-tiger-history-001", "龙虎榜席位历史", "tushare_top_inst", "2026-07-10"),
        EvidenceSource("margin-001", "融资融券", "tushare_margin_detail", "2026-07-10"),
        EvidenceSource("northbound-001", "北向持股", "tushare_hk_hold", "2026-07-10"),
        EvidenceSource("flow-001", "资金分档", "tushare_moneyflow", "2026-07-10"),
        EvidenceSource("flow-history-001", "主力资金历史", "tushare_moneyflow", "2026-07-10"),
        EvidenceSource("margin-history-001", "融资余额历史", "tushare_margin_detail", "2026-07-10"),
        EvidenceSource("northbound-history-001", "北向变化历史", "tushare_hk_hold", "2026-07-10"),
        EvidenceSource("intraday-bars-001", "分时", "akshare_intraday", "2026-07-10 14:55:00"),
        EvidenceSource("order-book-001", "盘口", "akshare_order_book", "2026-07-10 14:55:00"),
        EvidenceSource("industry-flow-001", "行业资金", "tushare_moneyflow_ind_ths", "2026-07-10"),
        EvidenceSource("industry-valuation-001", "行业估值", "tushare_daily_basic", "2026-07-10"),
        EvidenceSource("peer-fund-001", "行业盈利", "tushare_fina_indicator", "2026-03-31"),
    ]


def _quality_reports() -> list[DataQualityReport]:
    return [
        DataQualityReport("tushare", "dragon_tiger", "passed", 1, 1, 1.0, "2026-07-10"),
        DataQualityReport("tushare", "dragon_tiger_history", "passed", 4, 4, 1.0, "2026-07-10"),
        DataQualityReport("tushare", "margin_financing", "passed", 1, 1, 1.0, "2026-07-10"),
        DataQualityReport("tushare", "northbound_holding", "passed", 1, 1, 1.0, "2026-07-10"),
        DataQualityReport("tushare", "capital_flow_history", "passed", 5, 5, 1.0, "2026-07-10"),
    ]


def _faction_score(committee: SkillInsight, name: str) -> int:
    return next(item["score"] for item in committee.details["factions"] if item["name"] == name)


if __name__ == "__main__":
    unittest.main()
