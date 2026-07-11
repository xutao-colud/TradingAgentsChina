from __future__ import annotations

import tempfile
import unittest

from app.memory.local_store import LocalMemoryStore
from app.market.realtime import SinaRealtimeQuoteClient
from app.llm.runtime import ModelRuntime
from app.web.server import ResearchWebApp


class ResearchWebAppTest(unittest.TestCase):
    def test_dashboard_service_runs_analysis_and_persists_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = ResearchWebApp(LocalMemoryStore(tmpdir))
            result = app.analyze(
                {
                    "symbol": "600519",
                    "analysis_date": "2026-07-10",
                    "question": "是否符合我的趋势回踩打法？",
                }
            )
            self.assertEqual(result["symbol"], "600519.SH")
            self.assertIn("memory_event_id", result)
            context = app.memory_store.build_context("600519.SH")
            self.assertEqual(context["recent_same_symbol_interactions"][0]["question"], "是否符合我的趋势回踩打法？")

    def test_dashboard_service_exports_and_imports_memory(self) -> None:
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as target_dir:
            source = ResearchWebApp(LocalMemoryStore(source_dir))
            source.analyze({"symbol": "600519", "analysis_date": "2026-07-10"})
            bundle = source.export_memory()

            target = ResearchWebApp(LocalMemoryStore(target_dir))
            counts = target.import_memory(bundle)
            self.assertEqual(counts["analysis"], 1)
            self.assertEqual(counts["interaction"], 1)

    def test_dashboard_service_switches_persisted_playbook(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = ResearchWebApp(LocalMemoryStore(tmpdir))
            result = app.activate_playbook({"playbook_id": "institutional_growth"})
            self.assertEqual(result["trading_profile"]["active_playbook"], "institutional_growth")
            self.assertEqual(app.playbooks()["active_playbook"], "institutional_growth")

    def test_dashboard_watchlist_account_and_real_time_refresh(self) -> None:
        response = 'var hq_str_sh600519="贵州茅台,10,1500,1515,0,0,0,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-07-11,14:30:00";'
        with tempfile.TemporaryDirectory() as tmpdir:
            app = ResearchWebApp(LocalMemoryStore(tmpdir), quote_client=SinaRealtimeQuoteClient(fetch_text=lambda url: response))
            app.add_watchlist({"symbol": "600519", "note": "核心观察"})
            app.update_cash_balance({"cash_balance": 5000})
            app.upsert_position({"symbol": "600519", "quantity": 10, "cost_price": 1480})
            market = app.refresh_market()
            self.assertEqual(market["watchlist"][0]["quote"]["price"], 1515.0)
            self.assertEqual(market["portfolio"]["daily_pnl"], 150.0)
            self.assertEqual(market["portfolio"]["cash_balance"], 5000.0)

    def test_dashboard_model_configuration_never_returns_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = ModelRuntime(f"{tmpdir}/model_settings.json")
            app = ResearchWebApp(LocalMemoryStore(tmpdir), model_runtime=runtime)
            status = app.configure_model({"provider_id": "glm", "api_key": "session-secret-key", "model": "glm-5.1"})
            self.assertEqual(status["active_provider"], "glm")
            self.assertNotIn("session-secret-key", str(status))

    def test_analysis_can_attach_labelled_realtime_context(self) -> None:
        response = 'var hq_str_sh600519="贵州茅台,10,1500,1515,0,0,0,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-07-11,14:30:00";'
        with tempfile.TemporaryDirectory() as tmpdir:
            app = ResearchWebApp(LocalMemoryStore(tmpdir), quote_client=SinaRealtimeQuoteClient(fetch_text=lambda url: response))
            result = app.analyze({"symbol": "600519", "analysis_date": "2026-07-10", "include_realtime": True})
            self.assertEqual(result["realtime_quote"]["source"], "sina")
            self.assertEqual(result["realtime_quote"]["price"], 1515.0)
