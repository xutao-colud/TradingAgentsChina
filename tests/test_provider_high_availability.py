from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.data.provider_health import ProviderCircuitBreaker
from app.data.providers.production_provider import ProductionMarketDataProvider, _fundamental_cache_complete, _usable_flow
from app.data.verified_cache import VerifiedDatasetCache
from app.schemas.report import DataQualityReport, DailyPrice, FundamentalSnapshot, MarketContext, MoneyFlowSnapshot


class _UnavailableMarketProvider:
    def __init__(self, *, configured: bool = False, reports: list[DataQualityReport] | None = None) -> None:
        self.configured = configured
        self._reports = list(reports or [])

    def get_market_context(self, analysis_date: str) -> MarketContext:
        return MarketContext(
            "上证指数", None, None, None, None, None, None, "数据不足", [],
            data_status="unavailable", as_of=None,
        )

    def get_data_quality_reports(self, symbol: str, analysis_date: str) -> list[DataQualityReport]:
        return list(self._reports)


class ProviderHighAvailabilityTest(unittest.TestCase):
    def test_current_day_replays_recent_verified_market_context_without_claiming_realtime(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = VerifiedDatasetCache(directory)
            cached_context = MarketContext(
                "上证指数", 0.6, 980_000_000_000, 3200, 1800, 65, 8, "修复", [],
                failed_breakout_rate=18.0,
                sealed_limit_up_rate=82.0,
                data_status="verified",
                as_of="2026-07-17",
            )
            cache.save(
                "market_context", "2026-07-17", cached_context,
                source_type="sina_market_center+tencent_index", as_of="2026-07-17",
            )
            breadth_failure = DataQualityReport(
                "akshare", "market_breadth_current", "failed", 0, 0, 0.0,
                as_of="2026-07-20", blocking=True,
            )
            provider = ProductionMarketDataProvider(
                tushare=_UnavailableMarketProvider(configured=False),
                akshare=_UnavailableMarketProvider(reports=[breadth_failure]),
                public_fallback=_UnavailableMarketProvider(),
                verified_cache=cache,
                today=lambda: date(2026, 7, 20),
            )

            context = provider.get_market_context("2026-07-20")
            reports = provider.get_data_quality_reports("000725.SZ", "2026-07-20")
            source = next(
                item for item in provider._evidence[("__market__", "2026-07-20")]
                if item.id == "market-001"
            )

            self.assertEqual(context.data_status, "latest_available")
            self.assertEqual(context.as_of, "2026-07-17")
            self.assertIn("2026-07-17", context.unavailable_reasons[0])
            self.assertEqual(source.as_of, "2026-07-17")
            self.assertIn("previous_session", source.source_type)
            self.assertFalse(next(item for item in reports if item.dataset == "market_breadth_current").blocking)

    def test_verified_cache_round_trips_a_list(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = VerifiedDatasetCache(directory)
            prices = [DailyPrice("2026-07-16", 10, 11, 9, 10.5, 100, 1000, 2.0)]

            cache.save("daily_prices", "000725.SZ-2026-07-16", prices, source_type="test", as_of="2026-07-16")
            loaded = cache.load_list("daily_prices", "000725.SZ-2026-07-16", lambda row: DailyPrice(**row))

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded[0], prices)
            self.assertEqual(loaded[1]["source_type"], "test")

    def test_incomplete_fundamental_cache_requires_source_refresh(self):
        incomplete = FundamentalSnapshot(1, 1, 1, 1, 1, 1, 1, 1, "稳定", revenue=100)
        complete = FundamentalSnapshot(
            1, 1, 1, 1, 1, 1, 1, 1, "稳定",
            revenue=100,
            asset_turnover=0.5,
            deducted_net_income=10,
        )

        self.assertFalse(_fundamental_cache_complete(incomplete))
        self.assertTrue(_fundamental_cache_complete(complete))

    def test_verified_cache_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = VerifiedDatasetCache(directory)
            prices = [DailyPrice("2026-07-16", 1, 2, 1, 2, 100, None, None)]
            cache.save("daily_prices", "000725.SZ-2026-07-16", prices, source_type="tencent", as_of="2026-07-16")
            path = next(cache.root.rglob("*.json"))
            path.write_text(path.read_text(encoding="utf-8").replace('"close": 2', '"close": 99'), encoding="utf-8")
            self.assertIsNone(cache.load_list("daily_prices", "000725.SZ-2026-07-16", lambda row: DailyPrice(**row)))

    def test_circuit_opens_after_configured_failures_and_closes_on_success(self):
        clock = lambda: datetime(2026, 7, 16, tzinfo=timezone.utc)
        breaker = ProviderCircuitBreaker(now=clock)
        for _ in range(breaker.failure_threshold):
            breaker.record("eastmoney", "daily_prices", succeeded=False)
        self.assertFalse(breaker.allows("eastmoney", "daily_prices"))
        breaker.record("eastmoney", "daily_prices", succeeded=True)
        self.assertTrue(breaker.allows("eastmoney", "daily_prices"))

    def test_verified_tick_direction_is_usable_but_not_relabelled_as_main_flow(self):
        flow = MoneyFlowSnapshot(
            None, None, None, "数据不足", None, "数据不足",
            as_of="2026-07-16",
            trade_direction_net_inflow=-12_000_000,
            trade_direction_gross_amount=500_000_000,
            flow_method="tick_price_direction",
        )
        self.assertTrue(_usable_flow(flow))
        self.assertIsNone(flow.main_net_inflow)

    def test_verified_money_flow_cache_is_replayed_as_capital_history(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = VerifiedDatasetCache(directory)
            for trade_date, amount in (("2026-07-16", 10_000_000), ("2026-07-17", -3_000_000)):
                cache.save(
                    "money_flow",
                    f"000725.SZ-{trade_date}",
                    MoneyFlowSnapshot(amount, None, None, "数据不足", None, "数据不足", as_of=trade_date),
                    source_type="test_verified_flow",
                    as_of=trade_date,
                )
            provider = ProductionMarketDataProvider(
                tushare=SimpleNamespace(configured=False),
                akshare=SimpleNamespace(),
                public_fallback=SimpleNamespace(),
                verified_cache=cache,
            )

            history = provider.get_capital_flow_history("000725.SZ", "2026-07-17")

            self.assertEqual([item.trade_date for item in history], ["2026-07-16", "2026-07-17"])
            self.assertEqual([item.main_net_inflow for item in history], [10_000_000, -3_000_000])


if __name__ == "__main__":
    unittest.main()
