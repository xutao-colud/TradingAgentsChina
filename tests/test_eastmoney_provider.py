from __future__ import annotations

import unittest
from datetime import datetime

from app.data.providers.eastmoney_provider import EastmoneyRealtimeMarketDataProvider
from app.graph.workflow import AShareResearchWorkflow
from app.market.stock_snapshot import EastmoneyStockSnapshotClient


QUOTE_PAYLOAD = '{"data":{"f43":759,"f44":834,"f45":759,"f46":816,"f47":38046199,"f48":30277260673.71,"f57":"000725","f58":"京东方Ａ","f60":815,"f116":281166450005.76,"f117":268436547948.03,"f127":"光学光电子","f128":"北京板块","f129":"物联网,OLED,人工智能","f168":1076,"f170":-687}}'
FLOW_PAYLOAD = '{"data":{"klines":["2026-07-10,-5088655104.0,4058282752.0,1030372352.0,-1231041536.0,-3857613568.0,-16.81,13.40,3.40,-4.07,-12.74,7.59,-6.87"]}}'
KLINE_PAYLOAD = '{"data":{"klines":["2026-07-06,8.21,7.76,8.52,7.74,37087421,29710846049.61,9.31,-7.40,-0.62,10.49","2026-07-07,7.66,7.58,7.84,7.45,28186977,21575002743.30,5.03,-2.32,-0.18,7.97","2026-07-08,7.69,7.63,7.90,7.26,33222878,25344613436.08,8.44,0.66,0.05,9.39","2026-07-09,7.71,8.15,8.18,7.71,37939905,30116575240.89,6.16,6.82,0.52,10.73","2026-07-10,8.16,7.59,8.34,7.59,38046199,30277260673.71,9.20,-6.87,-0.56,10.76"]}}'


class EastmoneyRealtimeMarketDataProviderTest(unittest.TestCase):
    def test_uses_real_quote_profile_kline_and_money_flow(self) -> None:
        responses = [QUOTE_PAYLOAD, FLOW_PAYLOAD]
        provider = EastmoneyRealtimeMarketDataProvider(
            snapshot_client=EastmoneyStockSnapshotClient(fetch_text=lambda url: responses.pop(0), now=lambda: datetime(2026, 7, 13, 10, 0, 0)),
            fetch_text=lambda url: KLINE_PAYLOAD,
        )

        profile = provider.get_stock_profile("000725.SZ")
        prices = provider.get_daily_prices("000725.SZ", "2026-07-10", lookback_days=30)
        flow = provider.get_money_flow("000725.SZ", "2026-07-10")
        sources = provider.get_evidence_sources("000725.SZ", "2026-07-10")

        self.assertEqual(profile.name, "京东方A")
        self.assertEqual(profile.industry, "光学光电子")
        self.assertEqual(profile.board, "main")
        self.assertEqual(profile.concepts, ["物联网", "OLED", "人工智能"])
        self.assertEqual(profile.concept_source_id, "profile-concept-001")
        self.assertEqual(prices[-1].close, 7.59)
        self.assertEqual(prices[-1].turnover_rate, 10.76)
        self.assertEqual(flow.main_net_inflow, -5088655104.0)
        self.assertEqual(sources[0].source_type, "eastmoney_push2his")
        self.assertTrue(any(source.id == "profile-concept-001" for source in sources))

    def test_workflow_no_longer_uses_offline_sample_price_for_known_symbol(self) -> None:
        responses = [QUOTE_PAYLOAD, FLOW_PAYLOAD]
        provider = EastmoneyRealtimeMarketDataProvider(
            snapshot_client=EastmoneyStockSnapshotClient(fetch_text=lambda url: responses.pop(0), now=lambda: datetime(2026, 7, 13, 10, 0, 0)),
            fetch_text=lambda url: KLINE_PAYLOAD,
        )

        report = AShareResearchWorkflow(provider).run("000725.SZ", "2026-07-10")
        technical = next(item for item in report.agent_findings if item.agent == "技术分析 Agent")

        self.assertEqual(report.name, "京东方A")
        self.assertTrue(any("最新收盘 7.59" in item for item in technical.evidence))
        self.assertFalse(any("14.35" in item for item in technical.evidence))

    def test_money_flow_can_load_even_when_quote_snapshot_fails(self) -> None:
        responses = ["not-json", FLOW_PAYLOAD]
        provider = EastmoneyRealtimeMarketDataProvider(
            snapshot_client=EastmoneyStockSnapshotClient(fetch_text=lambda url: responses.pop(0), now=lambda: datetime(2026, 7, 13, 10, 0, 0)),
            fetch_text=lambda url: KLINE_PAYLOAD,
        )

        flow = provider.get_money_flow("000725.SZ", "2026-07-10")
        sources = provider.get_evidence_sources("000725.SZ", "2026-07-10")

        self.assertEqual(flow.main_net_inflow, -5088655104.0)
        self.assertEqual(sources[1].source_type, "eastmoney_push2his")

    def test_money_flow_falls_back_without_crashing_when_public_provider_fails(self) -> None:
        responses = ["not-json"]

        def fetch_text(url: str) -> str:
            if responses:
                return responses.pop(0)
            raise OSError("provider unavailable")

        provider = EastmoneyRealtimeMarketDataProvider(
            snapshot_client=EastmoneyStockSnapshotClient(fetch_text=fetch_text, now=lambda: datetime(2026, 7, 13, 10, 0, 0)),
            fetch_text=lambda url: KLINE_PAYLOAD,
        )

        flow = provider.get_money_flow("000725.SZ", "2026-07-10")
        sources = provider.get_evidence_sources("000725.SZ", "2026-07-10")

        self.assertEqual(flow.main_net_inflow, 8000000)
        self.assertEqual(sources[1].source_type, "offline_sample")

    def test_daily_price_uses_snapshot_not_offline_sample_when_kline_fails(self) -> None:
        responses = [QUOTE_PAYLOAD, FLOW_PAYLOAD]
        provider = EastmoneyRealtimeMarketDataProvider(
            snapshot_client=EastmoneyStockSnapshotClient(fetch_text=lambda url: responses.pop(0), now=lambda: datetime(2026, 7, 13, 10, 0, 0)),
            fetch_text=lambda url: "not-json",
        )

        prices = provider.get_daily_prices("000725.SZ", "2026-07-10", lookback_days=30)
        sources = provider.get_evidence_sources("000725.SZ", "2026-07-10")

        self.assertEqual(prices[-1].close, 7.59)
        self.assertFalse(any(price.close == 14.35 for price in prices))
        self.assertEqual(sources[0].source_type, "eastmoney_snapshot")

    def test_snapshot_is_not_relabelled_as_a_different_historical_date(self) -> None:
        responses = [QUOTE_PAYLOAD, FLOW_PAYLOAD]
        provider = EastmoneyRealtimeMarketDataProvider(
            snapshot_client=EastmoneyStockSnapshotClient(fetch_text=lambda url: responses.pop(0), now=lambda: datetime(2026, 7, 13, 10, 0, 0)),
            fetch_text=lambda url: "not-json",
        )

        prices = provider.get_daily_prices("000725.SZ", "2026-07-09", lookback_days=30)
        sources = provider.get_evidence_sources("000725.SZ", "2026-07-09")

        self.assertEqual(prices, [])
        self.assertEqual(sources[0].source_type, "unavailable")

    def test_short_snapshot_history_forces_report_to_data_insufficient(self) -> None:
        responses = [QUOTE_PAYLOAD, FLOW_PAYLOAD]
        provider = EastmoneyRealtimeMarketDataProvider(
            snapshot_client=EastmoneyStockSnapshotClient(fetch_text=lambda url: responses.pop(0), now=lambda: datetime(2026, 7, 13, 10, 0, 0)),
            fetch_text=lambda url: "not-json",
        )

        report = AShareResearchWorkflow(provider).run("000725.SZ", "2026-07-10")

        self.assertEqual(report.data_status, "数据不足")
        self.assertEqual(report.conclusion, "证据不足")


if __name__ == "__main__":
    unittest.main()
