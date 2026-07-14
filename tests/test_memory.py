import json
import tempfile
import unittest
from pathlib import Path

from app.graph.workflow import build_sample_workflow
from app.memory.local_store import LocalMemoryStore
from app.memory.models import FeedbackEvent, TradingProfile


class LocalMemoryStoreTest(unittest.TestCase):
    def test_save_analysis_creates_profile_and_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalMemoryStore(tmpdir)
            report = build_sample_workflow().run("600519", "2026-07-10")
            event = store.save_analysis(report, user_query="分析贵州茅台", model_name="deterministic-mvp")

            profile_path = Path(tmpdir) / "trading_profile.json"
            analysis_path = Path(tmpdir) / "analysis_events.jsonl"
            self.assertTrue(profile_path.exists())
            self.assertTrue(analysis_path.exists())
            rows = [json.loads(line) for line in analysis_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows[0]["id"], event.id)
            self.assertEqual(rows[0]["payload"]["report"]["symbol"], "600519.SH")

    def test_build_context_returns_profile_and_recent_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalMemoryStore(tmpdir)
            store.save_profile(TradingProfile(favorite_themes=["AI", "机器人"]))
            report = build_sample_workflow().run("600519", "2026-07-10")
            store.save_analysis(report)
            context = store.build_context("600519.SH")

            self.assertEqual(context["trading_profile"]["favorite_themes"], ["AI", "机器人"])
            self.assertEqual(len(context["recent_same_symbol_reports"]), 1)

    def test_record_feedback_appends_feedback_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalMemoryStore(tmpdir)
            feedback = store.record_feedback(
                FeedbackEvent(symbol="600519.SH", feedback_type="rule", user_comment="我不追高位连板")
            )
            feedback_path = Path(tmpdir) / "feedback_events.jsonl"
            rows = [json.loads(line) for line in feedback_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows[0]["id"], feedback.id)
            self.assertEqual(rows[0]["feedback_type"], "rule")

    def test_explicit_preference_updates_profile_but_outcome_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalMemoryStore(tmpdir)
            store.record_feedback(
                FeedbackEvent(
                    symbol="600519.SH",
                    feedback_type="preference",
                    user_comment="我不喜欢追高，更偏好趋势回踩低吸",
                )
            )
            profile = store.load_profile()
            self.assertIn("追高", profile.avoid_patterns)
            self.assertIn("趋势回踩", profile.preferred_setups)
            self.assertEqual(profile.version, 2)

            store.record_feedback(
                FeedbackEvent(
                    symbol="600519.SH",
                    feedback_type="outcome",
                    user_comment="10日后收益为 3%",
                    outcome_return_pct=3.0,
                    outcome_days=10,
                )
            )
            self.assertEqual(store.load_profile().version, 2)

    def test_portable_bundle_preserves_profile_and_interaction_history(self) -> None:
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as target_dir:
            source = LocalMemoryStore(source_dir)
            source.record_feedback(
                FeedbackEvent(
                    symbol="600519.SH",
                    feedback_type="preference",
                    user_comment="我不喜欢追高，倾向趋势回踩低吸",
                )
            )
            report = build_sample_workflow().run("600519", "2026-07-10", source.load_profile())
            analysis = source.save_analysis(report, user_query="分析贵州茅台")
            source.save_interaction_summary(report, "分析贵州茅台", analysis.id)
            bundle_path = Path(source_dir) / "my-a-share-memory.json"
            source.export_bundle(bundle_path)

            target = LocalMemoryStore(target_dir)
            counts = target.import_bundle(bundle_path)
            self.assertEqual(counts, {"analysis": 1, "feedback": 1, "interaction": 1})
            self.assertIn("追高", target.load_profile().avoid_patterns)
            context = target.build_context("600519.SH")
            self.assertEqual(context["recent_same_symbol_interactions"][0]["question"], "分析贵州茅台")

            repeated_counts = target.import_bundle(bundle_path)
            self.assertEqual(repeated_counts, {"analysis": 0, "feedback": 0, "interaction": 0})

    def test_active_playbook_is_persisted_and_portable(self) -> None:
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as target_dir:
            source = LocalMemoryStore(source_dir)
            source.set_active_playbook("institutional_growth")
            bundle = source.export_bundle()
            target = LocalMemoryStore(target_dir)
            target.import_bundle(bundle)
            self.assertEqual(target.load_profile().active_playbook, "institutional_growth")

    def test_watchlist_and_portfolio_are_portable(self) -> None:
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as target_dir:
            source = LocalMemoryStore(source_dir)
            source.add_watchlist("600519", "核心观察")
            source.set_cash_balance(10000)
            source.upsert_position("600519", quantity=100, cost_price=1500)
            target = LocalMemoryStore(target_dir)
            target.import_bundle(source.export_bundle())
            self.assertEqual(target.load_watchlist()[0]["symbol"], "600519.SH")
            self.assertEqual(target.load_portfolio()["cash_balance"], 10000.0)
            self.assertEqual(target.load_portfolio()["positions"][0]["quantity"], 100.0)

    def test_outcome_feedback_adapts_to_consent_gated_strategy_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalMemoryStore(tmpdir)
            report = build_sample_workflow().run("600519", "2026-07-10", store.load_profile())
            event = store.save_analysis(report)
            store.record_feedback(
                FeedbackEvent(
                    symbol="600519.SH",
                    feedback_type="outcome",
                    user_comment="10 日复盘",
                    analysis_report_id=event.id,
                    outcome_return_pct=3.2,
                    outcome_days=10,
                )
            )
            outcomes = store.local_strategy_outcomes(aggregate_consent=True)
            self.assertEqual(len(outcomes), 1)
            self.assertEqual(outcomes[0].analysis_report_id, event.id)
            self.assertEqual(outcomes[0].playbook_id, "trend_core")
            self.assertTrue(outcomes[0].aggregate_consent)
            self.assertEqual(outcomes[0].market_regime, report.market_regime)
            self.assertIn("市场周期 Agent", outcomes[0].agent_scores)

    def test_replay_keeps_original_report_and_later_outcome_side_by_side(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalMemoryStore(tmpdir)
            report = build_sample_workflow().run("600519", "2026-07-10", store.load_profile())
            event = store.save_analysis(report)
            store.record_feedback(
                FeedbackEvent(
                    symbol="600519.SH",
                    feedback_type="outcome",
                    user_comment="复盘结果",
                    analysis_report_id=event.id,
                    outcome_return_pct=1.2,
                    outcome_days=5,
                )
            )

            replay = store.replay_analysis(event.id)

            self.assertEqual(replay["replay_status"], "outcome_recorded")
            self.assertEqual(replay["report_snapshot"]["symbol"], "600519.SH")
            self.assertEqual(len(replay["feedback_events"]), 1)


if __name__ == "__main__":
    unittest.main()
