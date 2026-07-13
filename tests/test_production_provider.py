from __future__ import annotations

import unittest

from app.data.providers.akshare_provider import AkshareSupplementProvider
from app.data.providers.production_provider import ProductionMarketDataProvider
from app.data.providers.tushare_provider import TushareMarketDataProvider
from test_akshare_provider import FakeAkshare
from test_tushare_provider import FakeTushare


class ProductionMarketDataProviderTest(unittest.TestCase):
    def test_merges_real_sources_without_sample_fallback(self) -> None:
        provider = ProductionMarketDataProvider(TushareMarketDataProvider(FakeTushare()), AkshareSupplementProvider(FakeAkshare()))

        signals = provider.get_market_signals("600519", "2026-07-10")
        flow = provider.get_money_flow("600519", "2026-07-10")
        sources = provider.get_evidence_sources("600519", "2026-07-10")

        self.assertEqual(signals.data_status, "verified")
        self.assertEqual(flow.northbound_signal, "北向持股增加")
        self.assertFalse(any(item.source_type == "offline_sample" for item in sources))
        self.assertTrue(any(item.source_type.startswith("tushare_") for item in sources))


if __name__ == "__main__":
    unittest.main()
