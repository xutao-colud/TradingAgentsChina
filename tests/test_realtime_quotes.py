from __future__ import annotations

import unittest

from app.market.realtime import SinaRealtimeQuoteClient


def _line(identifier: str, name: str, previous: str, price: str) -> str:
    fields = [name, "10.00", previous, price, "10.50", "9.80", "0", "0", "123456", "1234567"] + ["0"] * 20 + ["2026-07-11", "14:36:00"]
    return f'var hq_str_{identifier}="{",".join(fields)}";'


class SinaRealtimeQuoteClientTest(unittest.TestCase):
    def test_parses_typed_quote_from_fixed_provider_response(self) -> None:
        client = SinaRealtimeQuoteClient(fetch_text=lambda url: _line("sh600519", "贵州茅台", "1500.00", "1515.00"))
        quote = client.fetch_quotes(["600519"])["600519.SH"]
        self.assertEqual(quote.name, "贵州茅台")
        self.assertEqual(quote.price, 1515.0)
        self.assertEqual(quote.change_pct, 1.0)
        self.assertEqual(quote.data_status, "real_time")

    def test_marks_missing_or_unsupported_symbols_unavailable(self) -> None:
        client = SinaRealtimeQuoteClient(fetch_text=lambda url: "")
        quote = client.fetch_quotes(["600519"])["600519.SH"]
        self.assertEqual(quote.data_status, "unavailable")
        with self.assertRaisesRegex(ValueError, "does not support BJ"):
            client.fetch_quotes(["430001.BJ"])
