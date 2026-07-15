from __future__ import annotations

import unittest
from datetime import date

from app.data.providers.akshare_provider import AkshareSupplementProvider
from app.data.raw_snapshots import InMemoryRawSnapshotStore


class FakeAkshare:
    def stock_zh_a_hist(self, **kwargs):
        return [{"日期": "2026-07-10", "开盘": 10, "最高": 12, "最低": 9, "收盘": 11, "成交量": 100, "成交额": 1000, "换手率": 3}]

    def stock_hsgt_hold_stock_em(self, **kwargs):
        return [{"代码": "600519", "今日持股-股数": 100, "今日持股-市值": 200, "增持估计-股数": 5}]

    def stock_ggcg_em(self, **kwargs):
        return [{"代码": "600519", "股东名称": "测试股东", "公告日": "2026-07-05", "持股变动信息-增减": "减持", "持股变动信息-变动数量": 10}]

    def stock_zh_a_disclosure_report_cninfo(self, **kwargs):
        return [
            {
                "代码": "600519",
                "公告标题": "2025年年度报告问询函",
                "公告时间": "2026-07-01 18:00:00",
                "公告链接": "https://example.test/inquiry",
            },
            {
                "代码": "600519",
                "公告标题": "2025年年度报告问询函回复公告",
                "公告时间": "2026-07-08 18:00:00",
                "公告链接": "https://example.test/reply",
            },
        ]

    def stock_zh_a_spot_em(self, **kwargs):
        return [
            {"代码": "600519", "涨跌幅": 1.2, "成交额": 1000},
            {"代码": "000001", "涨跌幅": -0.5, "成交额": 2000},
        ]

    def stock_zh_index_spot_em(self, **kwargs):
        return [{"代码": "000001", "涨跌幅": 0.4}]

    def stock_zt_pool_em(self, **kwargs):
        return [
            {"代码": "000001", "连板数": 1, "炸板次数": 0, "首次封板时间": "09:25:00"},
            {"代码": "000002", "连板数": 2, "炸板次数": 1, "首次封板时间": "10:01:00"},
        ]

    def stock_zt_pool_dtgc_em(self, **kwargs):
        return [{"代码": "000003"}]

    def stock_zt_pool_zbgc_em(self, **kwargs):
        return [{"代码": "000004"}]


class AkshareSupplementProviderTest(unittest.TestCase):
    def test_public_supplement_has_traceable_northbound_and_holding_events(self) -> None:
        provider = AkshareSupplementProvider(client=FakeAkshare(), enable_slow_bulk_queries=True)
        signals = provider.get_market_signals("600519", "2026-07-10")

        self.assertEqual(signals.data_status, "verified")
        self.assertEqual(signals.northbound_holding.holding_change, 5)
        self.assertEqual(signals.corporate_events[0].impact, "negative")
        self.assertEqual(signals.evidence_sources[0].source_type, "akshare_stock_hsgt_hold_stock_em")

    def test_daily_bars_are_mapped_without_sample_fallback(self) -> None:
        provider = AkshareSupplementProvider(client=FakeAkshare())
        self.assertEqual(provider.get_daily_prices("600519", "2026-07-10", 30)[0].close, 11)

    def test_cninfo_announcements_keep_type_time_url_and_snapshot_provenance(self) -> None:
        provider = AkshareSupplementProvider(client=FakeAkshare())

        items = provider.get_announcements("600519", "2026-07-10")
        sources = provider.get_evidence_sources("600519", "2026-07-10")

        self.assertEqual([item.event_type for item in items], ["inquiry", "inquiry_reply"])
        self.assertTrue(all(item.published_at <= "2026-07-10" for item in items))
        self.assertTrue(all(item.url for item in items))
        self.assertTrue(all(item.snapshot_ids for item in sources))
        quality = next(
            item for item in provider.get_data_quality_reports("600519", "2026-07-10")
            if item.dataset == "announcements"
        )
        self.assertEqual(quality.status, "passed")

    def test_cninfo_earnings_forecast_is_classified_and_enriched_with_real_detail_fields(self) -> None:
        class ForecastAkshare(FakeAkshare):
            def stock_zh_a_disclosure_report_cninfo(self, **kwargs):
                return [{
                    "代码": "000725",
                    "公告标题": "2026年半年度业绩预告",
                    "公告时间": "2026-07-09 19:05:00",
                    "公告链接": "https://example.test/forecast",
                }]

            def stock_yjyg_em(self, **kwargs):
                self.forecast_date = kwargs["date"]
                return [{
                    "股票代码": "000725",
                    "股票简称": "京东方A",
                    "预测指标": "归属于上市公司股东的净利润",
                    "业绩变动": "预计2026年1-6月归母净利润盈利:500,000万元至550,000万元，同比上升54%至69%",
                    "预测数值": 5_250_000_000,
                    "业绩变动幅度": 61.5,
                    "业绩变动原因": "显示业务经营改善。",
                    "预告类型": "预增",
                    "上年同期值": 3_246_890_000,
                    "公告日期": "2026-07-09",
                }]

        client = ForecastAkshare()
        provider = AkshareSupplementProvider(client=client)

        items = provider.get_announcements("000725", "2026-07-15")
        item = items[0]
        sources = provider.get_evidence_sources("000725", "2026-07-15")

        self.assertEqual(client.forecast_date, "20260630")
        self.assertEqual(item.event_type, "earnings_forecast")
        self.assertEqual(item.report_period, "2026-06-30")
        self.assertEqual(item.published_timestamp, "2026-07-09T19:05:00")
        self.assertEqual(item.forecast_net_profit_min_yuan, 5_000_000_000)
        self.assertEqual(item.forecast_net_profit_max_yuan, 5_500_000_000)
        self.assertEqual(item.sentiment, "positive")
        self.assertTrue(item.supporting_source_ids)
        self.assertTrue(any(source.source_type == "akshare_stock_yjyg_em" for source in sources))
        detail_quality = next(
            report for report in provider.get_data_quality_reports("000725", "2026-07-15")
            if report.dataset == "earnings_forecast_details"
        )
        self.assertEqual(detail_quality.status, "passed")

    def test_partial_cninfo_channel_failure_keeps_valid_records_as_warning(self) -> None:
        class PartialAkshare(FakeAkshare):
            def stock_zh_a_disclosure_report_cninfo(self, **kwargs):
                if kwargs["market"] == "监管":
                    raise OSError("regulatory endpoint unavailable")
                return super().stock_zh_a_disclosure_report_cninfo(**kwargs)

        provider = AkshareSupplementProvider(client=PartialAkshare())

        items = provider.get_announcements("600519", "2026-07-10")
        quality = next(
            report for report in provider.get_data_quality_reports("600519", "2026-07-10")
            if report.dataset == "announcements"
        )

        self.assertEqual(len(items), 2)
        self.assertEqual(quality.status, "warning")
        self.assertEqual(quality.valid_records, 2)
        self.assertTrue(any(issue.code == "provider_coverage_incomplete" for issue in quality.issues))

    def test_current_market_breadth_uses_real_snapshot_interfaces(self) -> None:
        provider = AkshareSupplementProvider(client=FakeAkshare(), today=lambda: date(2026, 7, 10))

        context = provider.get_market_context("2026-07-10")
        sources = provider.get_evidence_sources("600519", "2026-07-10")

        self.assertEqual(context.data_status, "verified")
        self.assertEqual((context.advancers, context.decliners), (1, 1))
        self.assertEqual((context.limit_up_count, context.limit_down_count), (2, 1))
        self.assertAlmostEqual(context.failed_breakout_rate, 100 / 3)
        self.assertEqual(context.board_ladder["2板"], 1)
        self.assertEqual(context.hot_money_cycle, "数据不足")
        self.assertTrue(any(item.id == "market-001" and item.snapshot_ids for item in sources))

    def test_current_market_snapshot_is_never_relabelled_as_history(self) -> None:
        provider = AkshareSupplementProvider(client=FakeAkshare(), today=lambda: date(2026, 7, 10))

        context = provider.get_market_context("2026-07-09")

        self.assertEqual(context.data_status, "unavailable")
        self.assertIsNone(context.advancers)

    def test_bulk_holder_snapshot_is_reused_within_configured_freshness(self) -> None:
        class CountingAkshare(FakeAkshare):
            holder_calls = 0

            def stock_ggcg_em(self, **kwargs):
                self.holder_calls += 1
                return super().stock_ggcg_em(**kwargs)

        client = CountingAkshare()
        store = InMemoryRawSnapshotStore()
        first = AkshareSupplementProvider(client=client, raw_store=store, enable_slow_bulk_queries=True)
        second = AkshareSupplementProvider(client=client, raw_store=store, enable_slow_bulk_queries=True)

        first.get_market_signals("600519", "2026-07-10")
        second.get_market_signals("600519", "2026-07-10")

        self.assertEqual(client.holder_calls, 1)

    def test_slow_global_holder_query_is_disabled_by_default(self) -> None:
        class RejectingAkshare(FakeAkshare):
            def stock_ggcg_em(self, **kwargs):
                raise AssertionError("slow global query must require explicit opt-in")

        provider = AkshareSupplementProvider(client=RejectingAkshare())

        signals = provider.get_market_signals("600519", "2026-07-10")
        quality = next(
            item for item in provider.get_data_quality_reports("600519", "2026-07-10")
            if item.dataset == "holder_trades"
        )

        self.assertEqual(signals.corporate_events, [])
        self.assertEqual(quality.status, "warning")
        self.assertTrue(any(item.code == "slow_bulk_query_disabled" for item in quality.issues))


if __name__ == "__main__":
    unittest.main()
