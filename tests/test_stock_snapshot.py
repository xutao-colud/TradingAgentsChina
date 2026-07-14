from __future__ import annotations

import json
import unittest
from datetime import datetime

from app.market.stock_snapshot import EastmoneyStockSnapshotClient


class StockSnapshotTest(unittest.TestCase):
    def test_fetch_snapshots_deduplicates_symbols_and_keeps_result_mapping(self) -> None:
        class RecordingClient(EastmoneyStockSnapshotClient):
            def __init__(self) -> None:
                self.seen: list[str] = []

            def fetch_snapshot(self, symbol: str):
                self.seen.append(symbol)
                return object()

        client = RecordingClient()

        snapshots = client.fetch_snapshots(["600519", "600519.SH", "000725"])

        self.assertEqual(set(snapshots), {"600519.SH", "000725.SZ"})
        self.assertEqual(set(client.seen), {"600519.SH", "000725.SZ"})
    def test_parses_quote_sector_and_order_size_flows(self) -> None:
        quote_payload = {
            "data": {
                "f43": 759,
                "f44": 834,
                "f45": 759,
                "f46": 816,
                "f47": 38046199,
                "f48": 30277260673.71,
                "f57": "000725",
                "f58": "京东方Ａ",
                "f60": 815,
                "f116": 281166450005.76,
                "f117": 268436547948.03,
                "f127": "光学光电子",
                "f128": "北京板块",
                "f129": "物联网,OLED,人工智能",
                "f168": 1076,
                "f170": -687,
            }
        }
        flow_payload = {
            "data": {
                "klines": [
                    "2026-07-10,-5088655104.0,4058282752.0,1030372352.0,-1231041536.0,-3857613568.0,-16.81,13.40,3.40,-4.07,-12.74,7.59,-6.87"
                ]
            }
        }
        responses = [json.dumps(quote_payload, ensure_ascii=False), json.dumps(flow_payload, ensure_ascii=False)]

        client = EastmoneyStockSnapshotClient(
            fetch_text=lambda url: responses.pop(0),
            now=lambda: datetime(2026, 7, 13, 10, 0, 0),
        )
        snapshot = client.fetch_snapshot("000725")

        self.assertEqual(snapshot.symbol, "000725.SZ")
        self.assertEqual(snapshot.name, "京东方A")
        self.assertEqual(snapshot.price, 7.59)
        self.assertEqual(snapshot.change_pct, -6.87)
        self.assertEqual(snapshot.industry, "光学光电子")
        self.assertEqual(snapshot.market_board, "深市主板")
        self.assertIn("OLED", snapshot.concepts)
        self.assertEqual(snapshot.data_status, "real_time")
        assert snapshot.money_flow is not None
        self.assertEqual(snapshot.money_flow.trade_date, "2026-07-10")
        self.assertEqual(snapshot.money_flow.main_net_inflow, -5088655104.0)
        self.assertEqual(snapshot.money_flow.visible_large_net_inflow, -5088655104.0)
        self.assertEqual(snapshot.money_flow.hidden_follow_net_inflow, 5088655104.0)

    def test_unavailable_snapshot_is_labelled(self) -> None:
        client = EastmoneyStockSnapshotClient(fetch_text=lambda url: "not-json")
        snapshot = client.fetch_snapshot("000725.SZ")

        self.assertEqual(snapshot.symbol, "000725.SZ")
        self.assertEqual(snapshot.data_status, "unavailable")
        self.assertTrue(snapshot.error)


if __name__ == "__main__":
    unittest.main()
