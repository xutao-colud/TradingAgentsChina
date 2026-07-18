from __future__ import annotations

import tempfile
import unittest
from datetime import datetime

from app.memory.local_store import LocalMemoryStore
from app.market.morning_radar import MorningMoneyRadarClient
from app.market.realtime import RealtimeQuote, SinaRealtimeQuoteClient
from app.market.stock_snapshot import EastmoneyStockSnapshotClient
from app.llm.runtime import ModelRuntime
from app.llm.prompt_contracts import EXPLANATION_COMPLETE_MARKER
from app.graph.workflow import build_sample_workflow
from app.web.server import ResearchWebApp, _is_local_machine_address, _is_loopback_address


class ResearchWebAppTest(unittest.TestCase):
    def test_model_secret_access_is_limited_to_loopback_clients(self) -> None:
        self.assertTrue(_is_loopback_address("127.0.0.1"))
        self.assertTrue(_is_loopback_address("::1"))
        self.assertFalse(_is_loopback_address("192.168.1.8"))
        self.assertFalse(_is_loopback_address("untrusted-host"))

    def test_model_secret_accepts_server_interface_but_rejects_other_lan_clients(self) -> None:
        server_addresses = {"127.0.0.1", "192.168.1.8", "::1"}
        self.assertTrue(_is_local_machine_address("127.0.0.1", server_addresses))
        self.assertTrue(_is_local_machine_address("192.168.1.8", server_addresses))
        self.assertTrue(_is_local_machine_address("::ffff:192.168.1.8", server_addresses))
        self.assertFalse(_is_local_machine_address("192.168.1.20", server_addresses))
        self.assertFalse(_is_local_machine_address("untrusted-host", server_addresses))

    def test_dashboard_runs_and_reads_persisted_opportunity_pool(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = ResearchWebApp(
                LocalMemoryStore(tmpdir),
                workflow=build_sample_workflow(),
                quote_client=SinaRealtimeQuoteClient(fetch_text=lambda url: ""),
                stock_snapshot_client=None,
            )
            app.add_watchlist({"symbol": "600519"})
            result = app.scan_opportunities(
                {
                    "analysis_date": "2026-07-14",
                    "symbols": ["000725"],
                    "include_radar": False,
                    "maximum_level": 1,
                }
            )

            self.assertEqual(result["level_counts"]["level1"], 2)
            self.assertEqual(app.opportunity_pool()["id"], result["id"])
            replay = app.replay_opportunity({"event_id": result["memory_event_id"]})
            self.assertEqual(replay["pool_snapshot"]["id"], result["id"])

    def test_dashboard_service_runs_analysis_and_persists_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = ResearchWebApp(LocalMemoryStore(tmpdir), workflow=build_sample_workflow())
            result = app.analyze(
                {
                    "symbol": "600519",
                    "analysis_date": "2026-07-10",
                    "question": "是否符合我的趋势回踩打法？",
                }
            )
            self.assertEqual(result["symbol"], "600519.SH")
            self.assertEqual(result["data_status"], "样例数据")
            self.assertEqual(result["user_question"], "是否符合我的趋势回踩打法？")
            committee = next(item for item in result["skill_insights"] if item["category"] == "committee")
            scenario = next(item for item in result["skill_insights"] if item["details"].get("mode") == "next_session_scenario")
            zones = next(item for item in result["skill_insights"] if item["details"].get("mode") == "price_observation_zones")
            self.assertEqual(committee["details"]["judge"]["discussion_topic"], "是否符合我的趋势回踩打法？")
            self.assertTrue(scenario["details"]["observational_only"])
            self.assertFalse(scenario["details"]["admitted"])
            self.assertTrue(zones["details"]["observational_only"])
            self.assertFalse(zones["details"]["admitted"])
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
            app.remove_position({"symbol": "600519"})
            self.assertEqual(app.portfolio()["position_count"], 0)

    def test_lightweight_ticker_refreshes_quotes_without_full_snapshot_flow(self) -> None:
        quote_payload = '{"data":{"f43":607,"f47":1000,"f48":607000,"f57":"000725","f58":"京东方A","f60":600,"f170":117}}'
        requested_urls: list[str] = []

        def fetch_text(url: str) -> str:
            requested_urls.append(url)
            return quote_payload

        with tempfile.TemporaryDirectory() as tmpdir:
            app = ResearchWebApp(
                LocalMemoryStore(tmpdir),
                stock_snapshot_client=EastmoneyStockSnapshotClient(
                    fetch_text=fetch_text,
                    now=lambda: datetime(2026, 7, 17, 10, 0, 0),
                ),
            )
            app.add_watchlist({"symbol": "000725"})
            app.upsert_position({"symbol": "000725", "quantity": 100, "cost_price": 5.8})
            result = app.refresh_ticker()

            self.assertEqual(result["tracked_count"], 1)
            self.assertEqual(result["quotes"]["000725.SZ"]["price"], 6.07)
            self.assertEqual(result["portfolio"]["positions"][0]["market_value"], 607.0)
            self.assertEqual(result["refresh_interval_ms"], 3000)
            self.assertEqual(len(requested_urls), 1)
            self.assertNotIn("fflow", requested_urls[0])

    def test_dashboard_watchlist_returns_sector_and_money_flow_snapshot(self) -> None:
        quote_payload = '{"data":{"f43":759,"f44":834,"f45":759,"f46":816,"f47":38046199,"f48":30277260673.71,"f57":"000725","f58":"京东方Ａ","f60":815,"f116":281166450005.76,"f117":268436547948.03,"f127":"光学光电子","f128":"北京板块","f129":"物联网,OLED,人工智能","f168":1076,"f170":-687}}'
        flow_payload = '{"data":{"klines":["2026-07-10,-5088655104.0,4058282752.0,1030372352.0,-1231041536.0,-3857613568.0,-16.81,13.40,3.40,-4.07,-12.74,7.59,-6.87"]}}'
        responses = [quote_payload, flow_payload]

        with tempfile.TemporaryDirectory() as tmpdir:
            app = ResearchWebApp(
                LocalMemoryStore(tmpdir),
                stock_snapshot_client=EastmoneyStockSnapshotClient(fetch_text=lambda url: responses.pop(0), now=lambda: datetime(2026, 7, 13, 10, 0, 0)),
            )
            app.add_watchlist({"symbol": "000725", "note": "面板方向"})
            market = app.refresh_market()
            snapshot = market["watchlist"][0]["snapshot"]

            self.assertEqual(snapshot["name"], "京东方A")
            self.assertEqual(snapshot["industry"], "光学光电子")
            self.assertEqual(snapshot["market_board"], "深市主板")
            self.assertIn("OLED", snapshot["concepts"])
            self.assertEqual(snapshot["money_flow"]["main_net_inflow"], -5088655104.0)
            self.assertEqual(snapshot["money_flow"]["visible_large_net_inflow"], -5088655104.0)
            self.assertEqual(snapshot["money_flow"]["hidden_follow_net_inflow"], 5088655104.0)
            self.assertEqual(market["source"], "eastmoney_push2+eastmoney_push2his")

    def test_dashboard_refresh_falls_back_to_sina_price_when_snapshot_is_unavailable(self) -> None:
        response = 'var hq_str_sz000725="京东方A,7.20,7.10,7.25,0,0,0,0,100,725000,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-07-13,10:15:00";'

        with tempfile.TemporaryDirectory() as tmpdir:
            app = ResearchWebApp(
                LocalMemoryStore(tmpdir),
                quote_client=SinaRealtimeQuoteClient(fetch_text=lambda url: response),
                stock_snapshot_client=EastmoneyStockSnapshotClient(fetch_text=lambda url: "not-json", now=lambda: datetime(2026, 7, 13, 10, 0, 0)),
            )
            app.add_watchlist({"symbol": "000725", "note": "验证价格兜底"})
            market = app.refresh_market()

            self.assertEqual(market["source"], "sina")
            self.assertEqual(market["watchlist"][0]["quote"]["source"], "sina")
            self.assertEqual(market["watchlist"][0]["quote"]["price"], 7.25)
            self.assertEqual(market["watchlist"][0]["snapshot"]["data_status"], "unavailable")

    def test_dashboard_model_configuration_never_returns_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = ModelRuntime(f"{tmpdir}/model_settings.json")
            app = ResearchWebApp(LocalMemoryStore(tmpdir), model_runtime=runtime)
            status = app.configure_model({"provider_id": "glm", "api_key": "session-secret-key", "model": "glm-5.1"})
            self.assertEqual(status["active_provider"], "glm")
            self.assertNotIn("session-secret-key", str(status))

    def test_analysis_binds_and_persists_the_selected_model_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            def fake_post(url, headers, payload):
                self.assertEqual(payload["model"], "qwen-plus")
                return {"choices": [{
                    "message": {"content": f"通义千问解释。\n{EXPLANATION_COMPLETE_MARKER}"},
                    "finish_reason": "stop",
                }]}

            runtime = ModelRuntime(f"{tmpdir}/model_settings.json", post_json=fake_post)
            runtime.configure("qwen", "session-secret-key", "qwen-plus")
            app = ResearchWebApp(
                LocalMemoryStore(tmpdir),
                workflow=build_sample_workflow(),
                model_runtime=runtime,
            )
            result = app.analyze(
                {
                    "symbol": "600519",
                    "analysis_date": "2026-07-10",
                    "model_explain": True,
                    "model_provider_id": "qwen",
                    "model_name": "qwen-plus",
                }
            )

            self.assertEqual(result["model_interpretation"], "通义千问解释。")
            self.assertEqual(result["model_execution"]["provider_id"], "qwen")
            self.assertEqual(result["model_execution"]["model"], "qwen-plus")
            saved = app.memory_store.recent_analyses("600519.SH", limit=1)[0]
            self.assertEqual(saved["payload"]["model_name"], "qwen:qwen-plus")

    def test_analysis_can_attach_labelled_realtime_context(self) -> None:
        response = 'var hq_str_sh600519="贵州茅台,10,1500,1515,0,0,0,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-07-11,14:30:00";'
        with tempfile.TemporaryDirectory() as tmpdir:
            app = ResearchWebApp(LocalMemoryStore(tmpdir), quote_client=SinaRealtimeQuoteClient(fetch_text=lambda url: response))
            result = app.analyze({"symbol": "600519", "analysis_date": "2026-07-10", "include_realtime": True})
            self.assertEqual(result["realtime_quote"]["source"], "sina")
            self.assertEqual(result["realtime_quote"]["price"], 1515.0)

    def test_dashboard_morning_radar_returns_shortline_lists(self) -> None:
        responses = [
            '{"data":{"diff":[{"f12":"BK1030","f14":"半导体","f3":2.1,"f62":1860000000,"f66":620000000,"f184":6.8}]}}',
            '{"data":{"diff":[{"f12":"BK0475","f14":"银行","f3":-0.7,"f62":-1350000000,"f66":-320000000,"f184":-4.3}]}}',
            '{"data":{"diff":[{"f12":"000725","f14":"京东方A","f2":4.68,"f3":3.1,"f6":3400000000,"f22":1.2,"f62":260000000,"f184":4.8}]}}',
        ]

        def fetch_text(url: str) -> str:
            return responses.pop(0)

        with tempfile.TemporaryDirectory() as tmpdir:
            app = ResearchWebApp(
                LocalMemoryStore(tmpdir),
                morning_radar_client=MorningMoneyRadarClient(fetch_text=fetch_text, now=lambda: datetime(2026, 7, 13, 9, 45, 0)),
            )
            radar = app.morning_radar({"limit": 3})
            self.assertEqual(radar["data_status"], "real_time")
            self.assertEqual(radar["top_inflow_sectors"][0]["name"], "半导体")
            self.assertEqual(radar["fast_movers"][0]["symbol"], "000725.SZ")

    def test_tracked_radar_enriches_individual_money_flow_without_claiming_sector_flow(self) -> None:
        quote_payload = '{"data":{"f43":702,"f44":717,"f45":666,"f46":690,"f47":29367326,"f48":20295239099.47,"f57":"000725","f58":"BOE","f60":683,"f116":281166450005.76,"f117":268436547948.03,"f127":"Optics","f128":"Beijing","f129":"OLED","f168":278,"f170":0}}'
        flow_payload = '{"data":{"klines":["2026-07-14,440532224.0,0,0,0,0,2.17,0,0,0,0,0"]}}'
        responses = [quote_payload, flow_payload]
        radar_client = MorningMoneyRadarClient(
            fetch_text=lambda url: (_ for _ in ()).throw(OSError("curl: (56) Failure when receiving data from the peer")),
            quote_fetcher=lambda symbols: {
                "000725.SZ": RealtimeQuote(
                    symbol="000725.SZ", name="BOE", price=7.02, previous_close=6.83,
                    change_pct=2.78, volume=29_367_326, amount=20_295_239_099.47,
                    trade_date="2026-07-14", trade_time="15:35:45",
                )
            },
            now=lambda: datetime(2026, 7, 14, 14, 0, 0),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            app = ResearchWebApp(
                LocalMemoryStore(tmpdir),
                morning_radar_client=radar_client,
                stock_snapshot_client=EastmoneyStockSnapshotClient(fetch_text=lambda url: responses.pop(0), now=lambda: datetime(2026, 7, 14, 14, 0, 0)),
            )
            app.add_watchlist({"symbol": "000725"})
            radar = app.morning_radar({"limit": 3})

            self.assertEqual(radar["data_status"], "tracked_universe")
            self.assertEqual(radar["source"], "sina_tracked_universe+eastmoney_stock_flow")
            self.assertEqual(radar["top_inflow_sectors"], [])
            self.assertEqual(radar["fast_movers"][0]["name"], "BOE")
            self.assertEqual(radar["fast_movers"][0]["main_net_inflow"], 440532224.0)
