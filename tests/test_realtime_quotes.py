from __future__ import annotations

import unittest
from datetime import datetime

from app.market.realtime import SinaRealtimeQuoteClient, TencentRealtimeQuoteClient


def _line(identifier: str, name: str, previous: str, price: str, trade_date: str = "2026-07-13") -> str:
    fields = [name, "10.00", previous, price, "10.50", "9.80", "0", "0", "123456", "1234567"] + ["0"] * 20 + [trade_date, "14:36:00"]
    return f'var hq_str_{identifier}="{",".join(fields)}";'


class SinaRealtimeQuoteClientTest(unittest.TestCase):
    def test_parses_typed_quote_from_fixed_provider_response(self) -> None:
        client = SinaRealtimeQuoteClient(
            fetch_text=lambda url: _line("sh600519", "贵州茅台", "1500.00", "1515.00"),
            now=lambda: datetime(2026, 7, 13, 10, 0, 0),
        )
        quote = client.fetch_quotes(["600519"])["600519.SH"]
        self.assertEqual(quote.name, "贵州茅台")
        self.assertEqual(quote.price, 1515.0)
        self.assertEqual(quote.change_pct, 1.0)
        self.assertEqual(quote.data_status, "real_time")

    def test_marks_old_trade_date_as_latest_available(self) -> None:
        client = SinaRealtimeQuoteClient(
            fetch_text=lambda url: _line("sz000725", "京东方A", "8.15", "7.59", trade_date="2026-07-10"),
            now=lambda: datetime(2026, 7, 12, 22, 0, 0),
        )
        quote = client.fetch_quotes(["000725"])["000725.SZ"]
        self.assertEqual(quote.price, 7.59)
        self.assertEqual(quote.data_status, "latest_available")

    def test_marks_missing_or_unsupported_symbols_unavailable(self) -> None:
        client = SinaRealtimeQuoteClient(fetch_text=lambda url: "")
        quote = client.fetch_quotes(["600519"])["600519.SH"]
        self.assertEqual(quote.data_status, "unavailable")
        with self.assertRaisesRegex(ValueError, "does not support BJ"):
            client.fetch_quotes(["430001.BJ"])

    def test_retries_transient_quote_fetch_failure(self) -> None:
        calls = 0

        def fetch_text(url: str) -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("connection reset")
            return _line("sh600519", "贵州茅台", "1500.00", "1515.00")

        client = SinaRealtimeQuoteClient(fetch_text=fetch_text, now=lambda: datetime(2026, 7, 13, 10, 0, 0))
        quote = client.fetch_quotes(["600519"])["600519.SH"]

        self.assertEqual(calls, 2)
        self.assertEqual(quote.data_status, "real_time")


class TencentRealtimeQuoteClientTest(unittest.TestCase):
    def test_parses_current_batch_quote_with_provider_timestamp(self) -> None:
        fields = [""] * 40
        fields[0] = "51"
        fields[1] = "京东方A"
        fields[2] = "000725"
        fields[3] = "5.79"
        fields[4] = "6.07"
        fields[6] = "26813210"
        fields[30] = "20260720101530"
        fields[32] = "-4.61"
        fields[35] = "5.79/26813210/15825022216"
        fields[37] = "1582502"
        response = f'v_sz000725="{"~".join(fields)}";'
        client = TencentRealtimeQuoteClient(
            fetch_text=lambda url: response,
            now=lambda: datetime(2026, 7, 20, 10, 16, 0),
        )

        quote = client.fetch_quotes(["000725"])["000725.SZ"]

        self.assertEqual(quote.name, "京东方A")
        self.assertEqual(quote.price, 5.79)
        self.assertEqual(quote.previous_close, 6.07)
        self.assertEqual(quote.change_pct, -4.61)
        self.assertEqual(quote.volume, 26_813_210)
        self.assertEqual(quote.amount, 15_825_022_216)
        self.assertEqual(quote.trade_date, "2026-07-20")
        self.assertEqual(quote.trade_time, "10:15:30")
        self.assertEqual(quote.data_status, "real_time")
        self.assertEqual(quote.source, "tencent")
