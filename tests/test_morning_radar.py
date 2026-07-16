from __future__ import annotations

import json
import unittest
from datetime import datetime

from app.market.morning_radar import MorningMoneyRadarClient, MorningRadarSnapshot, SectorFlow, sample_morning_radar
from app.market.realtime import RealtimeQuote


def _payload(rows):
    return json.dumps({"data": {"diff": rows}}, ensure_ascii=False)


class MorningRadarTest(unittest.TestCase):
    def test_parses_sector_flows_and_fast_movers(self) -> None:
        responses: list[str] = [
            _payload([{"f12": "BK1030", "f14": "半导体", "f3": 2.1, "f62": 1860000000, "f66": 620000000, "f184": 6.8}]),
            _payload([{"f12": "BK0475", "f14": "银行", "f3": -0.7, "f62": -1350000000, "f66": -320000000, "f184": -4.3}]),
            _payload([{"f12": "000725", "f14": "京东方A", "f2": 4.68, "f3": 3.1, "f6": 3400000000, "f22": 1.2, "f62": 260000000, "f184": 4.8}]),
        ]

        def fetch_text(url: str) -> str:
            self.assertIn("push2.eastmoney.com", url)
            return responses.pop(0)

        client = MorningMoneyRadarClient(fetch_text=fetch_text, now=lambda: datetime(2026, 7, 13, 9, 45, 0))
        snapshot = client.fetch_snapshot(limit=3)

        self.assertEqual(snapshot.data_status, "real_time")
        self.assertEqual(snapshot.market_phase, "早盘主升观察")
        self.assertEqual(snapshot.top_inflow_sectors[0].name, "半导体")
        self.assertEqual(snapshot.top_outflow_sectors[0].main_net_inflow, -1350000000)
        self.assertEqual(snapshot.fast_movers[0].symbol, "000725.SZ")
        self.assertIn("京东方A", snapshot.shortline_read)

    def test_returns_unavailable_when_provider_fails(self) -> None:
        client = MorningMoneyRadarClient(fetch_text=lambda url: "not-json", now=lambda: datetime(2026, 7, 13, 8, 30, 0))
        snapshot = client.fetch_snapshot()

        self.assertEqual(snapshot.data_status, "unavailable")
        self.assertEqual(snapshot.source, "eastmoney_push2")
        self.assertTrue(snapshot.error)
        self.assertFalse(snapshot.top_inflow_sectors)
        self.assertIn("不展示样例", snapshot.shortline_read)

    def test_uses_scoped_quote_fallback_when_market_wide_provider_disconnects(self) -> None:
        def quotes(symbols: list[str]) -> dict[str, RealtimeQuote]:
            self.assertEqual(symbols, ["000725.SZ"])
            return {
                "000725.SZ": RealtimeQuote(
                    symbol="000725.SZ",
                    name="BOE",
                    price=7.02,
                    previous_close=6.83,
                    change_pct=2.78,
                    volume=29_367_326,
                    amount=20_295_239_099,
                    trade_date="2026-07-14",
                    trade_time="15:35:45",
                )
            }

        client = MorningMoneyRadarClient(
            fetch_text=lambda url: (_ for _ in ()).throw(OSError("curl: (56) Failure when receiving data from the peer")),
            quote_fetcher=quotes,
            now=lambda: datetime(2026, 7, 14, 14, 0, 0),
        )
        snapshot = client.fetch_snapshot(limit=3, fallback_symbols=["000725.SZ"])

        self.assertEqual(snapshot.data_status, "tracked_universe")
        self.assertEqual(snapshot.source, "sina_tracked_universe")
        self.assertEqual(snapshot.as_of, "2026-07-14T15:35:45")
        self.assertEqual(snapshot.fast_movers[0].symbol, "000725.SZ")
        self.assertIsNone(snapshot.fast_movers[0].main_net_inflow)
        self.assertNotIn("curl: (56)", snapshot.error or "")

    def test_uses_post_market_sector_fallback_before_tracked_quotes(self) -> None:
        def post_market_fallback(limit: int, now: datetime) -> MorningRadarSnapshot:
            self.assertEqual(limit, 3)
            self.assertEqual(now, datetime(2026, 7, 14, 14, 0, 0))
            return MorningRadarSnapshot(
                as_of="2026-07-11",
                source="tushare_moneyflow_ind_ths",
                data_status="latest_available",
                market_phase="最近完整交易日行业资金快照",
                top_inflow_sectors=[SectorFlow("881100.TI", "半导体", 2.0, 800_000_000, None)],
                top_outflow_sectors=[SectorFlow("881103.TI", "银行", -0.6, -300_000_000, None)],
                fast_movers=[],
                shortline_read="盘后行业资金快照。",
                risks=["非盘中数据。"],
            )

        client = MorningMoneyRadarClient(
            fetch_text=lambda url: (_ for _ in ()).throw(OSError("provider unavailable")),
            secondary_fetcher=post_market_fallback,
            now=lambda: datetime(2026, 7, 14, 14, 0, 0),
        )
        snapshot = client.fetch_snapshot(limit=3, fallback_symbols=["000725.SZ"])

        self.assertEqual(snapshot.source, "tushare_moneyflow_ind_ths")
        self.assertEqual(snapshot.data_status, "latest_available")
        self.assertEqual(snapshot.as_of, "2026-07-11")
        self.assertEqual(snapshot.top_inflow_sectors[0].name, "半导体")
        self.assertFalse(snapshot.fast_movers)
        self.assertIn("东方财富盘中全市场列表暂不可用", snapshot.error or "")

    def test_uses_configured_delayed_eastmoney_host_before_non_eastmoney_fallbacks(self) -> None:
        delayed_responses = [
            _payload([{"f12": "BK1030", "f14": "半导体", "f3": 2.1, "f62": 1_860_000_000, "f66": 620_000_000, "f184": 6.8}]),
            _payload([{"f12": "BK0475", "f14": "银行", "f3": -0.7, "f62": -1_350_000_000, "f66": -320_000_000, "f184": -4.3}]),
            _payload([{"f12": "000725", "f14": "京东方A", "f2": 6.38, "f3": -9.12, "f6": 19_757_452_199, "f22": 0.2, "f62": -2_361_915_648, "f184": -11.95}]),
        ]

        def fetch_text(url: str) -> str:
            if "push2delay.eastmoney.com" in url:
                return delayed_responses.pop(0)
            raise OSError("primary peer disconnected")

        client = MorningMoneyRadarClient(fetch_text=fetch_text, now=lambda: datetime(2026, 7, 15, 10, 0, 0))
        snapshot = client.fetch_snapshot(limit=3)

        self.assertEqual(snapshot.source, "eastmoney_push2delay")
        self.assertEqual(snapshot.top_inflow_sectors[0].name, "半导体")
        self.assertEqual(snapshot.fast_movers[0].name, "京东方A")

    def test_public_provider_data_is_latest_available_outside_trading_hours(self) -> None:
        responses = [
            _payload([{"f12": "BK1030", "f14": "半导体", "f3": 2.1, "f62": 1860000000, "f66": 620000000, "f184": 6.8}]),
            _payload([{"f12": "BK0475", "f14": "银行", "f3": -0.7, "f62": -1350000000, "f66": -320000000, "f184": -4.3}]),
            _payload([{"f12": "000725", "f14": "京东方A", "f2": 4.68, "f3": 3.1, "f6": 3400000000, "f22": 1.2, "f62": 260000000, "f184": 4.8}]),
        ]
        client = MorningMoneyRadarClient(fetch_text=lambda url: responses.pop(0), now=lambda: datetime(2026, 7, 12, 10, 0, 0))
        snapshot = client.fetch_snapshot(limit=3)

        self.assertEqual(snapshot.data_status, "latest_available")
        self.assertEqual(snapshot.market_phase, "非交易日")
        self.assertTrue(any("最近可用交易数据" in item for item in snapshot.risks))

    def test_sample_snapshot_is_explicitly_labelled(self) -> None:
        snapshot = sample_morning_radar(error="offline")
        self.assertEqual(snapshot.data_status, "sample")
        self.assertIn("离线样例", " ".join(snapshot.risks))


if __name__ == "__main__":
    unittest.main()
