from __future__ import annotations

import unittest
from datetime import date

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

    def test_akshare_price_evidence_survives_market_signal_merge(self) -> None:
        class NoPriceTushare(FakeTushare):
            def daily(self, **kwargs):
                if "ts_code" in kwargs:
                    return []
                return super().daily(**kwargs)

        provider = ProductionMarketDataProvider(
            TushareMarketDataProvider(NoPriceTushare()),
            AkshareSupplementProvider(FakeAkshare()),
        )

        prices = provider.get_daily_prices("600519.SH", "2026-07-10", 120)
        provider.get_market_signals("600519.SH", "2026-07-10")
        sources = provider.get_evidence_sources("600519.SH", "2026-07-10")

        self.assertTrue(prices)
        price_source = next(item for item in sources if item.id == "price-001")
        self.assertEqual(price_source.source_type, "akshare_stock_zh_a_hist")
        self.assertEqual(price_source.as_of, "2026-07-10")

    def test_current_market_context_falls_back_to_real_akshare_not_sample(self) -> None:
        provider = ProductionMarketDataProvider(
            TushareMarketDataProvider(pro_client=None),
            AkshareSupplementProvider(FakeAkshare(), today=lambda: date(2026, 7, 10)),
        )

        context = provider.get_market_context("2026-07-10")
        sources = provider.get_evidence_sources("600519.SH", "2026-07-10")

        self.assertEqual(context.data_status, "verified")
        self.assertEqual(context.as_of, "2026-07-10")
        self.assertTrue(any(item.id == "market-001" and item.source_type.startswith("akshare_") for item in sources))
        self.assertFalse(any(item.source_type == "offline_sample" for item in sources))


if __name__ == "__main__":
    unittest.main()
