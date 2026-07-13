from __future__ import annotations

import unittest
from datetime import date

from app.data.providers.akshare_provider import AkshareSupplementProvider
from app.schemas.report import IntradayBar, IntradaySnapshot, OrderBookLevel
from app.skills.intraday_analysis import analyze_intraday_snapshot


class IntradayAnalysisTest(unittest.TestCase):
    def test_computes_vwap_volume_distribution_and_book_imbalance(self) -> None:
        bars = [
            IntradayBar(f"2026-07-13 09:{30 + index * 5:02d}:00", 10, 10.2, 9.9, 10 + index * 0.02, 100 + index * 10, (100 + index * 10) * (10 + index * 0.02))
            for index in range(8)
        ]
        snapshot = IntradaySnapshot(
            "verified", bars[-1].timestamp, bars,
            bids=[OrderBookLevel(10.15, 2000)], asks=[OrderBookLevel(10.16, 500)],
            source_ids=["intraday-bars-akshare-001", "order-book-akshare-001"],
        )
        result = analyze_intraday_snapshot(snapshot)

        self.assertEqual(result.stage, "买方承接偏强")
        self.assertGreater(result.details["order_book_imbalance"], 0)
        self.assertIsNotNone(result.details["vwap"])
        self.assertIn("五档委托可以撤单", result.risks[0])

    def test_historical_date_is_not_filled_with_live_snapshot(self) -> None:
        provider = AkshareSupplementProvider(client=object(), today=lambda: date(2026, 7, 13))
        snapshot = provider.get_intraday_snapshot("600519", "2026-07-10")
        self.assertEqual(snapshot.data_status, "unavailable")
        self.assertFalse(snapshot.bars)

    def test_akshare_rows_keep_timestamp_and_order_book(self) -> None:
        class Fake:
            def stock_zh_a_hist_min_em(self, **kwargs):
                return [
                    {"时间": f"2026-07-13 09:{30 + index * 5:02d}:00", "开盘": 10, "最高": 10.2, "最低": 9.9, "收盘": 10.1, "成交量": 100, "成交额": 1010}
                    for index in range(6)
                ]

            def stock_bid_ask_em(self, **kwargs):
                return [{"item": "buy_1", "value": 10.1}, {"item": "buy_1_vol", "value": 200}, {"item": "sell_1", "value": 10.2}, {"item": "sell_1_vol", "value": 100}]

        provider = AkshareSupplementProvider(client=Fake(), today=lambda: date(2026, 7, 13))
        snapshot = provider.get_intraday_snapshot("600519", "2026-07-13")
        self.assertEqual(snapshot.data_status, "verified")
        self.assertEqual(len(snapshot.bars), 6)
        self.assertEqual(snapshot.bids[0].volume, 200)
        self.assertIn("order-book-akshare-001", snapshot.source_ids)


if __name__ == "__main__":
    unittest.main()
