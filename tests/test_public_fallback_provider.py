from __future__ import annotations

import json
import unittest
from datetime import date
from urllib.parse import parse_qs, urlsplit

from app.data.providers.public_fallback_provider import PublicFallbackMarketDataProvider


class _Frame:
    def __init__(self, rows):
        self.rows = rows

    def to_dict(self, orient="records"):
        return list(self.rows)


class _PublicClient:
    def stock_financial_abstract(self, **kwargs):
        rows = []
        metrics = {
            "营业总收入": (120.0, 100.0),
            "归母净利润": (12.0, 10.0),
            "扣非净利润": (10.0, 9.0),
            "经营现金流量净额": (15.0, 9.0),
            "资产总计": (200.0, 180.0),
            "股东权益合计(净资产)": (100.0, 90.0),
            "总资产周转率": (0.60, 0.55),
            "权益乘数(含少数股权的净资产)": (2.0, 2.0),
            "商誉": (5.0, 5.0),
            "净资产收益率(ROE)": (12.0, 10.0),
            "毛利率": (30.0, 28.0),
            "资产负债率": (50.0, 50.0),
        }
        for name, (current, prior) in metrics.items():
            rows.append({"选项": "常用指标", "指标": name, "20260331": current, "20250331": prior})
        return _Frame(rows)

    def stock_fund_flow_individual(self, **kwargs):
        return _Frame([{
            "股票代码": 725,
            "股票简称": "京东方A",
            "换手率": "2.50%",
            "流入资金": "10亿",
            "流出资金": "7亿",
            "净额": "3亿",
            "成交额": "20亿",
        }])


class _SinaTickFallbackClient(_PublicClient):
    def __init__(self):
        self.tick_calls = 0

    def stock_fund_flow_individual(self, **kwargs):
        # THS free rankings can legitimately omit a requested stock.
        return _Frame([{"��Ʊ����": 600000, "����": "1��"}])

    def stock_intraday_sina(self, **kwargs):
        self.tick_calls += 1
        return _Frame([
            {"ticktime": "09:25:00", "price": 6.25, "volume": 1_000_000, "prev_price": 0, "kind": "U"},
            {"ticktime": "09:30:03", "price": 6.28, "volume": 100_000, "prev_price": 6.27, "kind": "U"},
            {"ticktime": "09:30:06", "price": 6.21, "volume": 50_000, "prev_price": 6.28, "kind": "D"},
            {"ticktime": "09:30:09", "price": 6.22, "volume": 20_000, "prev_price": 6.21, "kind": "E"},
        ])


class _SinaIntradayClient(_SinaTickFallbackClient):
    def stock_intraday_sina(self, **kwargs):
        self.tick_calls += 1
        return _Frame([
            {"ticktime": f"09:{minute:02d}:03", "price": 6.20 + index * 0.01, "volume": 10_000, "prev_price": 6.20, "kind": "U"}
            for index, minute in enumerate((30, 35, 40, 45, 50, 55))
        ])


class _TransientFlowClient(_PublicClient):
    def __init__(self):
        self.calls = 0

    def stock_fund_flow_individual(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return _Frame([])
        return super().stock_fund_flow_individual(**kwargs)


class _IndustryClient(_PublicClient):
    def stock_industry_change_cninfo(self, **kwargs):
        return _Frame([
            {
                "新证券简称": "京东方A",
                "行业中类": "面板",
                "行业大类": "光学光电子",
                "行业次类": "电子",
                "行业门类": "信息技术",
                "分类标准编码": "008014",
                "变更日期": "2021-12-17",
            }
        ])

    def stock_fund_flow_industry(self, **kwargs):
        return _Frame([
            {"行业": "通信", "净额": 43.92, "行业-涨跌幅": 0.4, "公司家数": 84},
            {"行业": "光学光电子", "净额": -15.86, "行业-涨跌幅": -6.43, "公司家数": 107},
            {"行业": "消费电子", "净额": -32.25, "行业-涨跌幅": -7.34, "公司家数": 97},
        ])


def _fetch(url: str) -> str:
    query = parse_qs(urlsplit(url).query)
    if "getHQNodeStockCount" in url:
        return json.dumps("3")
    if "getHQNodeData" in url:
        return json.dumps([
            {"symbol": "sz000725", "code": "000725", "name": "京东方A", "trade": "6.60", "settlement": "6.00", "open": "6.60", "high": "6.60", "low": "6.60", "changepercent": "10.00", "amount": 2_000_000_000},
            {"symbol": "sh600000", "code": "600000", "name": "浦发银行", "trade": "9.00", "settlement": "9.10", "open": "9.10", "high": "9.20", "low": "8.95", "changepercent": "-1.10", "amount": 1_000_000_000},
            {"symbol": "sh600001", "code": "600001", "name": "测试股份", "trade": "10.50", "settlement": "10.00", "open": "10.10", "high": "11.00", "low": "10.00", "changepercent": "5.00", "amount": 500_000_000},
        ])
    code = query["param"][0].split(",", 1)[0]
    quote = [""] * 34
    quote[1] = "京东方A" if code == "sz000725" else "上证指数"
    quote[32] = "0.50"
    rows = [["2026-07-15", "6.00", "6.10", "6.20", "5.90", "100"], ["2026-07-16", "6.10", "6.20", "6.30", "6.00", "120"]]
    return json.dumps({"code": 0, "data": {code: {"qfqday": rows, "qt": {code: quote}}}})


class PublicFallbackMarketDataProviderTest(unittest.TestCase):
    def setUp(self):
        self.provider = PublicFallbackMarketDataProvider(
            client=_PublicClient(), fetch_text=_fetch, today=lambda: date(2026, 7, 16)
        )

    def test_independent_sources_fill_required_evidence_without_samples(self):
        symbol = "000725.SZ"
        analysis_date = "2026-07-16"
        prices = self.provider.get_daily_prices(symbol, analysis_date, 120)
        fundamentals = self.provider.get_fundamentals(symbol, analysis_date)
        flow = self.provider.get_money_flow(symbol, analysis_date)
        market = self.provider.get_market_context(analysis_date)
        sources = {item.id: item for item in self.provider.get_evidence_sources(symbol, analysis_date)}

        self.assertEqual(len(prices), 2)
        self.assertIsNone(prices[-1].amount)
        self.assertAlmostEqual(fundamentals.revenue_growth_yoy, 20.0)
        self.assertEqual(fundamentals.deducted_net_income, 10.0)
        self.assertAlmostEqual(fundamentals.non_recurring_profit_ratio, 100 / 6)
        self.assertEqual(fundamentals.asset_turnover, 0.6)
        self.assertEqual(fundamentals.equity_multiplier, 2.0)
        self.assertEqual(flow.main_net_inflow, 300_000_000)
        self.assertEqual(market.data_status, "verified")
        self.assertEqual((market.advancers, market.decliners), (2, 1))
        self.assertEqual((market.limit_up_count, market.broken_limit_up_count), (1, 1))
        self.assertEqual(market.one_price_limit_up_count, 1)
        self.assertAlmostEqual(market.failed_breakout_rate, 50.0)
        self.assertAlmostEqual(market.sealed_limit_up_rate, 50.0)
        self.assertAlmostEqual(market.median_stock_change_pct, 5.0)
        self.assertIsNotNone(market.amount_weighted_change_pct)
        self.assertEqual(set(sources), {"price-001", "fund-001", "flow-001", "market-001"})
        self.assertTrue(all("sample" not in item.source_type for item in sources.values()))
        quality = next(
            item for item in self.provider.get_data_quality_reports(symbol, analysis_date)
            if item.dataset == "fundamentals_public"
        )
        self.assertEqual(quality.status, "passed")

    def test_historical_market_breadth_is_not_relabelled(self):
        context = self.provider.get_market_context("2026-07-15")
        self.assertEqual(context.data_status, "unavailable")
        self.assertIsNone(context.as_of)

    def test_missing_ths_target_falls_back_to_sina_ticks_without_fake_main_flow(self):
        provider = PublicFallbackMarketDataProvider(
            client=_SinaTickFallbackClient(), fetch_text=_fetch, today=lambda: date(2026, 7, 16)
        )
        flow = provider.get_money_flow("000725.SZ", "2026-07-16")
        source = next(
            item for item in provider.get_evidence_sources("000725.SZ", "2026-07-16")
            if item.id == "flow-001"
        )
        ths_snapshot = next(
            item for item in provider.get_raw_snapshots("000725.SZ", "2026-07-16")
            if item.interface == "stock_fund_flow_individual"
        )

        self.assertIsNone(flow.main_net_inflow)
        self.assertEqual(flow.trade_direction_net_inflow, 317_500)
        self.assertEqual(flow.flow_method, "tick_price_direction")
        self.assertEqual(source.source_type, "sina_tick_trade_direction")
        self.assertEqual(ths_snapshot.status, "failed")
        self.assertIn("absent from provider coverage", ths_snapshot.error)

    def test_empty_flow_response_is_not_cached_as_success(self):
        client = _TransientFlowClient()
        provider = PublicFallbackMarketDataProvider(
            client=client, fetch_text=_fetch, today=lambda: date(2026, 7, 16)
        )
        first = provider.get_money_flow("000725.SZ", "2026-07-16")
        second = provider.get_money_flow("000725.SZ", "2026-07-16")

        self.assertIsNone(first.main_net_inflow)
        self.assertEqual(second.main_net_inflow, 300_000_000)
        self.assertEqual(client.calls, 2)

    def test_sina_ticks_are_reused_for_money_flow_and_intraday_bars(self):
        client = _SinaIntradayClient()
        provider = PublicFallbackMarketDataProvider(
            client=client, fetch_text=_fetch, today=lambda: date(2026, 7, 16)
        )

        flow = provider.get_money_flow("000725.SZ", "2026-07-16")
        snapshot = provider.get_intraday_snapshot("000725.SZ", "2026-07-16")

        self.assertEqual(client.tick_calls, 1)
        self.assertIsNotNone(flow.trade_direction_net_inflow)
        self.assertEqual(snapshot.data_status, "verified")
        self.assertEqual(len(snapshot.bars), 6)
        self.assertEqual(snapshot.source_ids, ["intraday-bars-sina-001"])

    def test_cninfo_classification_exactly_matches_public_industry_flow(self):
        provider = PublicFallbackMarketDataProvider(
            client=_IndustryClient(), fetch_text=_fetch, today=lambda: date(2026, 7, 17)
        )

        profile = provider.get_stock_profile("000725.SZ")
        context = provider.get_industry_context("000725.SZ", "2026-07-17")

        self.assertEqual(profile.industry, "光学光电子")
        self.assertEqual(context.data_status, "verified")
        target = next(item for item in context.flow_observations if item.industry == "光学光电子")
        self.assertEqual(target.net_amount, -1_586_000_000)
        self.assertEqual(context.source_ids, ["profile-001", "industry-flow-001"])


if __name__ == "__main__":
    unittest.main()
