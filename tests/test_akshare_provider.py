from __future__ import annotations

import unittest

from app.data.providers.akshare_provider import AkshareSupplementProvider


class FakeAkshare:
    def stock_zh_a_hist(self, **kwargs):
        return [{"日期": "2026-07-10", "开盘": 10, "最高": 12, "最低": 9, "收盘": 11, "成交量": 100, "成交额": 1000, "换手率": 3}]

    def stock_hsgt_hold_stock_em(self, **kwargs):
        return [{"代码": "600519", "今日持股-股数": 100, "今日持股-市值": 200, "增持估计-股数": 5}]

    def stock_ggcg_em(self, **kwargs):
        return [{"代码": "600519", "股东名称": "测试股东", "持股变动信息-增减": "减持", "持股变动信息-变动数量": 10}]

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


class AkshareSupplementProviderTest(unittest.TestCase):
    def test_public_supplement_has_traceable_northbound_and_holding_events(self) -> None:
        provider = AkshareSupplementProvider(client=FakeAkshare())
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


if __name__ == "__main__":
    unittest.main()
