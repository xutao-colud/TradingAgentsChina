from __future__ import annotations

import json
import unittest
from datetime import datetime

from app.market.morning_radar import MorningMoneyRadarClient, sample_morning_radar


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
