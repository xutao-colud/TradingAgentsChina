from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace

from app.market.morning_radar import FastMover, MorningRadarSnapshot
from app.graph.workflow import build_sample_workflow
from app.market.stock_snapshot import StockMoneyFlowBreakdown, StockRealtimeSnapshot
from app.memory.local_store import LocalMemoryStore
from app.memory.models import TradingProfile
from app.opportunities.models import OpportunityCandidate
from app.opportunities.pipeline import OpportunityPipeline
from app.opportunities.scanner import CandidateObservation, OpportunityScanner
from app.schemas.report import AnalysisReport, MarketContext, SkillInsight


def _market(status: str = "verified") -> MarketContext:
    return MarketContext(
        index_name="test-index",
        index_change_pct=0.5,
        total_amount=900_000_000_000,
        advancers=3000,
        decliners=2000,
        limit_up_count=60,
        limit_down_count=10,
        hot_money_cycle="repair",
        policy_themes=[],
        data_status=status,
        as_of="2026-07-14",
    )


def _snapshot(symbol: str = "600519.SH", *, complete: bool = True) -> StockRealtimeSnapshot:
    flow = StockMoneyFlowBreakdown(
        trade_date="2026-07-14",
        main_net_inflow=80_000_000,
        super_large_net_inflow=40_000_000,
        large_net_inflow=40_000_000,
        medium_net_inflow=-20_000_000,
        small_net_inflow=-60_000_000,
        main_net_inflow_ratio=8.0,
        visible_large_net_inflow=80_000_000,
        hidden_follow_net_inflow=-80_000_000,
    )
    return StockRealtimeSnapshot(
        symbol=symbol,
        name="test-stock",
        price=100.0,
        previous_close=98.0,
        change_pct=2.04,
        open=99.0,
        high=101.0,
        low=98.5,
        volume=10_000_000,
        amount=1_500_000_000 if complete else None,
        turnover_rate=3.2 if complete else None,
        market_cap=100_000_000_000,
        float_market_cap=80_000_000_000,
        industry="AI",
        market_board="main",
        region="Shanghai",
        concepts=["AI", "computing"],
        money_flow=flow,
        as_of="2026-07-14T10:00:00",
        source="test-real-source",
        data_status="real_time",
    )


def _report(level: int = 2) -> AnalysisReport:
    insights = [
        SkillInsight("readiness", "data_quality", "verified", 90, "ok", "continue"),
        SkillInsight("evidence", "quality", "usable", 88, "ok", "continue"),
        SkillInsight("composite", "decision", "strong", 82, "ok", "observe"),
        SkillInsight("profile", "personalization", "fit", 80, "ok", "observe"),
    ]
    return AnalysisReport(
        symbol="600519.SH",
        name="test-stock",
        analysis_date="2026-07-14",
        data_status="verified",
        market_regime="repair",
        fundamental_score=80,
        technical_score=80,
        capital_flow_score=80,
        sentiment_score=70,
        theme_score=75,
        risk_level="medium",
        conclusion="Current evidence supports further observation.",
        confidence=0.7,
        action_plan="Observe only; no automatic trade instruction.",
        bull_case=["verified supporting evidence"],
        bear_case=["market regime can change"],
        risk_factors=["snapshot and report may become stale"],
        invalid_conditions=["evidence timestamps no longer align"],
        agent_findings=[],
        evidence_sources=[],
        skill_insights=insights,
        analysis_level=level,
    )


class _Provider:
    data_mode = "production"

    def get_market_context(self, analysis_date: str) -> MarketContext:
        return _market()


class _Workflow:
    def __init__(self) -> None:
        self.provider = _Provider()
        self.committee_calls = 0

    def prepare_state(self, symbol, analysis_date, trading_profile=None, user_question=None):
        return type("State", (), {"symbol": symbol, "user_question": user_question})()

    def evaluate_state(self, state, include_committee=False):
        return _report(2)

    def convene_committee(self, state) -> None:
        self.committee_calls += 1

    def build_report(self, state, analysis_level=3):
        return _report(analysis_level)


class OpportunityScannerTest(unittest.TestCase):
    def test_l1_is_profile_aware_and_traceable(self) -> None:
        candidate = OpportunityScanner().scan(
            CandidateObservation(_snapshot(), ["watchlist", "explicit"]),
            "2026-07-14",
            TradingProfile(favorite_themes=["AI"]),
            _market(),
        )

        self.assertGreaterEqual(candidate.level1_score, 60)
        self.assertEqual(candidate.profile_fit_score, 100)
        self.assertTrue(candidate.evidence)
        self.assertTrue(candidate.counterpoints or candidate.risks)
        self.assertTrue(candidate.invalidation_conditions)

    def test_missing_snapshot_fields_are_not_neutralized(self) -> None:
        candidate = OpportunityScanner().scan(
            CandidateObservation(_snapshot(complete=False), ["explicit"]),
            "2026-07-14",
            TradingProfile(favorite_themes=["AI"]),
            _market(),
        )

        self.assertEqual(candidate.stage, "excluded")
        self.assertEqual(candidate.data_status, "insufficient")
        self.assertLess(candidate.data_coverage, 0.55)
        self.assertTrue(any("coverage" in item for item in candidate.counterpoints))

    def test_lifecycle_marks_material_score_deterioration_as_retreat(self) -> None:
        scanner = OpportunityScanner()
        baseline = scanner.scan(
            CandidateObservation(_snapshot(), ["explicit"]),
            "2026-07-13",
            TradingProfile(favorite_themes=["AI"]),
            _market(),
        )
        previous = replace(baseline, level1_score=100, stage="climax")
        weak_flow = replace(
            _snapshot().money_flow,
            main_net_inflow=-80_000_000,
            main_net_inflow_ratio=-8.0,
        )
        weakened_snapshot = replace(
            _snapshot(),
            change_pct=-2.0,
            amount=500_000_000,
            money_flow=weak_flow,
        )
        current = scanner.scan(
            CandidateObservation(weakened_snapshot, ["explicit"]),
            "2026-07-14",
            TradingProfile(favorite_themes=["AI"]),
            _market(),
            previous=previous,
        )

        self.assertEqual(current.stage, "retreat")


class OpportunityPipelineTest(unittest.TestCase):
    def test_unavailable_fast_snapshot_falls_back_to_provider_daily_data(self) -> None:
        class UnavailableClient:
            def fetch_snapshots(self, symbols):
                return {
                    symbol: replace(
                        _snapshot(symbol),
                        price=None,
                        change_pct=None,
                        amount=None,
                        turnover_rate=None,
                        money_flow=None,
                        data_status="unavailable",
                    )
                    for symbol in symbols
                }

        with tempfile.TemporaryDirectory() as tmpdir:
            result = OpportunityPipeline(
                build_sample_workflow(),
                LocalMemoryStore(tmpdir),
                stock_snapshot_client=UnavailableClient(),
            ).run(
                "2026-07-14",
                explicit_symbols=["600519"],
                include_radar=False,
                maximum_level=1,
            )

            self.assertEqual(result["level_counts"]["level1"], 1)
            self.assertEqual(result["candidates"][0]["data_coverage"], 1.0)
            self.assertEqual(result["candidates"][0]["data_status"], "sample")

    def test_pipeline_promotes_only_gated_candidates_and_persists_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalMemoryStore(tmpdir)
            store.add_watchlist("600519")
            workflow = _Workflow()
            pipeline = OpportunityPipeline(workflow, store)

            result = pipeline.run(
                "2026-07-14",
                explicit_symbols=["600519"],
                include_radar=False,
                maximum_level=3,
                snapshots={"600519.SH": _snapshot()},
            )

            self.assertEqual(result["level_counts"]["level3"], 1)
            candidate = result["candidates"][0]
            self.assertEqual(candidate["highest_completed_level"], 3)
            self.assertIn("watchlist", candidate["source_tags"])
            self.assertIn("explicit", candidate["source_tags"])
            self.assertIsNotNone(candidate["level2_analysis_event_id"])
            self.assertIsNotNone(candidate["level3_analysis_event_id"])
            self.assertEqual(workflow.committee_calls, 1)
            replay = store.replay_opportunity_run(result["memory_event_id"])
            self.assertEqual(replay["pool_snapshot"]["id"], result["id"])
            self.assertIn("not win rates", replay["guardrail"])
            bundle = store.export_bundle()
            with tempfile.TemporaryDirectory() as target_dir:
                imported = LocalMemoryStore(target_dir)
                counts = imported.import_bundle(bundle)
                self.assertEqual(counts["opportunity"], 1)
                self.assertEqual(imported.load_opportunity_pool()["id"], result["id"])

    def test_sample_or_unavailable_market_context_blocks_level3(self) -> None:
        class SampleProvider(_Provider):
            data_mode = "sample"

        with tempfile.TemporaryDirectory() as tmpdir:
            workflow = _Workflow()
            workflow.provider = SampleProvider()
            pipeline = OpportunityPipeline(workflow, LocalMemoryStore(tmpdir))
            result = pipeline.run(
                "2026-07-14",
                explicit_symbols=["600519"],
                include_radar=False,
                maximum_level=3,
                snapshots={"600519.SH": _snapshot()},
            )

            self.assertEqual(result["market_data_status"], "sample")
            self.assertEqual(result["level_counts"]["level2"], 1)
            self.assertEqual(result["level_counts"]["level3"], 0)
            self.assertEqual(workflow.committee_calls, 0)

    def test_insufficient_market_context_blocks_level3(self) -> None:
        class InsufficientProvider(_Provider):
            def get_market_context(self, analysis_date: str) -> MarketContext:
                return _market("insufficient")

        with tempfile.TemporaryDirectory() as tmpdir:
            workflow = _Workflow()
            workflow.provider = InsufficientProvider()
            result = OpportunityPipeline(workflow, LocalMemoryStore(tmpdir)).run(
                "2026-07-14",
                explicit_symbols=["600519"],
                include_radar=False,
                maximum_level=3,
                snapshots={"600519.SH": _snapshot()},
            )

            self.assertEqual(result["pipeline_status"], "partial")
            self.assertEqual(result["level_counts"]["level3"], 0)
            self.assertTrue(any("market_context" in item for item in result["errors"]))

    def test_verified_radar_candidate_joins_user_universe(self) -> None:
        mover = FastMover("000725.SZ", "radar-stock", 8.0, 3.0, 1.0, 900_000_000, 50_000_000, 5.0, "verified anomaly")
        radar = MorningRadarSnapshot(
            as_of="2026-07-14T10:00:00",
            source="test-radar",
            data_status="real_time",
            market_phase="continuous-auction",
            top_inflow_sectors=[],
            top_outflow_sectors=[],
            fast_movers=[mover],
            shortline_read="observation only",
            risks=[],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            result = OpportunityPipeline(_Workflow(), LocalMemoryStore(tmpdir)).run(
                "2026-07-14",
                include_radar=True,
                maximum_level=1,
                radar_snapshot=radar,
                snapshots={"000725.SZ": _snapshot("000725.SZ")},
            )
            self.assertEqual(result["candidates"][0]["source_tags"], ["radar"])
            self.assertTrue(any("radar" in item["source_id"] for item in result["candidates"][0]["evidence"]))


if __name__ == "__main__":
    unittest.main()
