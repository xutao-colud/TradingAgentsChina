from __future__ import annotations

import unittest
from datetime import date, timedelta

from app.agents.capital_flow_agent import analyze_capital_flow
from app.data.providers.tushare_provider import TushareMarketDataProvider
from app.skills.sentiment_dynamics import analyze_sentiment_dynamics


class FakeTushare:
    def stock_basic(self, **kwargs):
        if "ts_code" in kwargs:
            return [{"ts_code": kwargs["ts_code"], "name": "测试股份", "industry": "电子", "list_date": "20200101", "list_status": "L"}]
        return [
            {"ts_code": code, "name": f"同行{index}", "industry": "电子", "list_date": "20200101", "list_status": "L"}
            for index, code in enumerate(("600519.SH", "600001.SH", "600002.SH", "600003.SH"), start=1)
        ]

    def daily(self, **kwargs):
        if "ts_code" not in kwargs:
            trade_date = kwargs["trade_date"]
            market_changes = {
                "20260706": [1.0, -2.0, -1.0, 0.5],
                "20260707": [2.0, 1.0, -1.5, -0.5],
                "20260708": [3.0, 2.0, 1.0, -1.0],
                "20260709": [4.0, 3.0, 2.0, -0.5],
                "20260710": [5.0, 4.0, 2.5, -0.2],
            }
            symbols = ["600001.SH", "600002.SH", "000001.SZ", "300001.SZ"]
            return [
                {"ts_code": symbol, "trade_date": trade_date, "pct_chg": change, "amount": 100_000 + index * 10_000}
                for index, (symbol, change) in enumerate(zip(symbols, market_changes[trade_date]))
            ]
        end = date(2026, 7, 10)
        return [
            {
                "trade_date": (end - timedelta(days=offset)).strftime("%Y%m%d"),
                "open": 10 + index * 0.04,
                "high": 10.8 + index * 0.04,
                "low": 9.6 + index * 0.04,
                "close": 10.4 + index * 0.04,
                "vol": 100 + index,
                "amount": 1000 + index * 10,
            }
            for index, offset in enumerate(range(129, -1, -1))
        ]

    def daily_basic(self, **kwargs):
        if "start_date" in kwargs:
            peer_offset = {
                "600519.SH": 0.0,
                "600001.SH": 1.0,
                "600002.SH": 2.0,
                "600003.SH": 3.0,
            }.get(kwargs.get("ts_code"), 0.0)
            return [
                {
                    "trade_date": trade_date,
                    "turnover_rate": 3.2,
                    "pe_ttm": 16 + index + peer_offset,
                    "pb": 1.6 + index * 0.1 + peer_offset * 0.05,
                }
                for index, trade_date in enumerate(
                    ("20260130", "20260227", "20260331", "20260430", "20260529", "20260710")
                )
            ]
        return [{"trade_date": "20260710", "turnover_rate": 3.2, "pe_ttm": 20, "pb": 2}]

    def fina_indicator(self, **kwargs):
        peer_values = {
            "600001.SH": (8, 10, 6, 20, 30),
            "600002.SH": (10, 12, 8, 30, 40),
            "600003.SH": (12, 14, 10, 40, 50),
        }
        values = peer_values.get(kwargs.get("ts_code"), (10, 12, 8, 30, 20))
        return [{
            "ts_code": kwargs.get("ts_code", "600519.SH"),
            "ann_date": "20260420",
            "end_date": "20260331",
            "or_yoy": values[0],
            "q_netprofit_yoy": values[1],
            "roe": values[2],
            "grossprofit_margin": values[3],
            "debt_to_assets": values[4],
            "ocf_yoy": 15,
        }]

    def income(self, **kwargs):
        return [{"ann_date": "20260420", "end_date": "20260331", "total_revenue": 200, "n_income": 20}]

    def balancesheet(self, **kwargs):
        return [{"ann_date": "20260420", "end_date": "20260331", "total_assets": 100, "total_hldr_eqy_exc_min_int": 50, "accounts_receiv": 20, "inventories": 10}]

    def cashflow(self, **kwargs):
        return [{"ann_date": "20260420", "end_date": "20260331", "n_cashflow_act": 30}]

    def moneyflow(self, **kwargs):
        if "start_date" in kwargs:
            return [
                {"trade_date": trade_date, "net_mf_amount": amount}
                for trade_date, amount in zip(
                    ("20260706", "20260707", "20260708", "20260709", "20260710"),
                    (10, 20, 30, 40, 50),
                )
            ]
        return [{
            "trade_date": "20260710", "net_mf_amount": 50,
            "buy_elg_amount": 100, "sell_elg_amount": 40,
            "buy_lg_amount": 80, "sell_lg_amount": 50,
            "buy_md_amount": 40, "sell_md_amount": 60,
            "buy_sm_amount": 30, "sell_sm_amount": 70,
        }]

    def moneyflow_ind_ths(self, **kwargs):
        return [
            {"trade_date": "20260710", "ts_code": "881100.TI", "industry": "半导体", "net_amount": 8, "pct_change": 2.0, "company_num": 80},
            {"trade_date": "20260710", "ts_code": "881101.TI", "industry": "电子", "net_amount": 6, "pct_change": 1.5, "company_num": 120},
            {"trade_date": "20260710", "ts_code": "881102.TI", "industry": "电池", "net_amount": 2, "pct_change": 0.5, "company_num": 45},
            {"trade_date": "20260710", "ts_code": "881103.TI", "industry": "银行", "net_amount": -3, "pct_change": -0.6, "company_num": 42},
        ]

    def cb_basic(self, **kwargs):
        return [{"ts_code": "123001.SZ", "bond_short_name": "测试转债", "stk_code": "300001.SZ", "conv_price": 10, "remain_size": 200_000_000, "maturity_date": "20300101"}]

    def cb_daily(self, **kwargs):
        return [{"ts_code": "123001.SZ", "trade_date": "20260710", "close": 120, "amount": 5000}]

    def index_daily(self, **kwargs):
        return [
            {"trade_date": trade_date, "pct_chg": change, "amount": 500000}
            for trade_date, change in [
                ("20260706", -0.8),
                ("20260707", -0.2),
                ("20260708", 0.3),
                ("20260709", 0.7),
                ("20260710", 1.1),
            ]
        ]

    def limit_list_d(self, **kwargs):
        trade_date = kwargs["trade_date"]
        rows = {
            "20260706": [("600001.SH", "U", 1), ("000001.SZ", "D", 0), ("600003.SH", "Z", 0)],
            "20260707": [("600001.SH", "U", 2), ("600002.SH", "U", 1), ("000001.SZ", "D", 0)],
            "20260708": [("600001.SH", "U", 3), ("600002.SH", "U", 2), ("300001.SZ", "U", 1)],
            "20260709": [("600001.SH", "U", 4), ("600002.SH", "U", 3), ("300001.SZ", "U", 2)],
            "20260710": [("600001.SH", "U", 5), ("600002.SH", "U", 4), ("300001.SZ", "U", 3)],
        }
        return [
            {
                "ts_code": symbol,
                "trade_date": trade_date,
                "limit": limit_type,
                "limit_times": limit_times,
                "open_times": 0 if limit_type == "U" and symbol == "600001.SH" else 2,
                "first_time": "09:25:00" if limit_type == "U" and symbol == "600001.SH" else "10:00:00" if limit_type == "U" else None,
            }
            for symbol, limit_type, limit_times in rows[trade_date]
        ]

    def stk_ah_comparison(self, **kwargs):
        return []

    def major_news(self, **kwargs):
        return [{"title": "人工智能产业支持政策发布", "content": "支持算力和大模型产业发展", "pub_time": "2026-07-10 10:00:00", "src": "official"}]

    def top_list(self, **kwargs):
        return [{"ts_code": "600519.SH", "trade_date": "20260710", "reason": "日涨幅偏离", "net_amount": 100}]

    def top_inst(self, **kwargs):
        return [{
            "ts_code": "600519.SH",
            "trade_date": "20260710",
            "reason": "日涨幅偏离",
            "exalter": "机构专用",
            "side": "0",
            "buy": 60,
            "sell": 10,
            "buy_rate": 6,
            "sell_rate": 1,
            "net_buy": 50,
        }]

    def margin_detail(self, **kwargs):
        if "start_date" in kwargs:
            return [
                {"trade_date": trade_date, "rzye": balance, "rqye": 10, "rzmre": 100, "rzche": 80}
                for trade_date, balance in zip(
                    ("20260706", "20260707", "20260708", "20260709", "20260710"),
                    (960, 970, 980, 990, 1000),
                )
            ]
        return [{"trade_date": "20260710", "rzye": 1000, "rqye": 10, "rzmre": 100, "rzche": 80}]

    def hk_hold(self, **kwargs):
        if "start_date" in kwargs:
            return [
                {"trade_date": trade_date, "vol": quantity}
                for trade_date, quantity in zip(
                    ("20260706", "20260707", "20260708", "20260709", "20260710"),
                    (500, 510, 525, 545, 570),
                )
            ]
        return [{"trade_date": "20260710", "vol": 570}]

    def forecast(self, **kwargs):
        return [{
            "ann_date": "20260709",
            "first_ann_date": "20260701",
            "end_date": "20260630",
            "type": "预增",
            "net_profit_min": 100,
            "net_profit_max": 120,
        }]

    def express(self, **kwargs):
        return [{"ann_date": "20260710", "end_date": "20260630", "n_income": 1_300_000}]

    def share_float(self, **kwargs):
        return [{"ann_date": "20260708", "float_share": 1000}]

    def stk_holdertrade(self, **kwargs):
        return [{"ann_date": "20260707", "holder_name": "大股东", "in_de": "DE", "change_vol": 200}]


class TushareMarketDataProviderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = TushareMarketDataProvider(pro_client=FakeTushare())

    def test_collects_real_domain_records_with_provenance(self) -> None:
        signals = self.provider.get_market_signals("600519", "2026-07-10")

        self.assertEqual(signals.data_status, "verified")
        self.assertEqual(signals.dragon_tiger[0].source_id, "dragon-tiger-001")
        self.assertEqual(signals.dragon_tiger[0].net_buy_amount, 100)
        self.assertEqual(signals.dragon_tiger[0].institution_net_amount, 50)
        self.assertEqual(signals.margin_financing.margin_balance, 1000)
        self.assertEqual(signals.northbound_holding.holding_change, 25)
        self.assertEqual({item.event_type for item in signals.corporate_events}, {"业绩预告", "业绩快报", "实际业绩", "限售解禁", "股东增减持"})
        self.assertTrue(any(item.id.startswith("event-forecast-") for item in signals.evidence_sources))
        self.assertEqual(next(item for item in signals.corporate_events if item.event_type == "业绩预告").impact, "positive")
        self.assertTrue(any(item.dataset == "dragon_tiger" and item.status == "passed" for item in signals.quality_reports))
        self.assertTrue(any(item.dataset == "margin_financing" and item.status == "passed" for item in signals.quality_reports))
        self.assertTrue(next(item for item in signals.evidence_sources if item.id == "dragon-tiger-001").snapshot_ids)
        self.assertTrue(next(item for item in signals.evidence_sources if item.id == "margin-001").snapshot_ids)

    def test_industry_context_has_rankable_flow_and_historical_valuation(self) -> None:
        context = self.provider.get_industry_context("600519", "2026-07-10")

        target = next(item for item in context.flow_observations if item.industry == "电子")
        self.assertEqual(context.data_status, "verified")
        self.assertEqual(target.net_amount, 600_000_000)
        self.assertEqual(len(context.valuation_history), 6)
        self.assertEqual(context.valuation_history[-1].sample_size, 4)
        self.assertIn("industry-flow-001", context.source_ids)
        self.assertIn("industry-valuation-001", context.source_ids)
        quality = {
            item.dataset: item.status
            for item in self.provider.get_data_quality_reports("600519", "2026-07-10")
        }
        self.assertEqual(quality["industry_flow"], "passed")
        self.assertEqual(quality["industry_valuation"], "passed")
        sources = {item.id: item for item in self.provider.get_evidence_sources("600519", "2026-07-10")}
        self.assertTrue(sources["industry-flow-001"].snapshot_ids)
        self.assertTrue(sources["industry-valuation-001"].snapshot_ids)

    def test_provider_exposes_capabilities_and_replayable_raw_snapshots(self) -> None:
        self.provider.get_market_signals("600519", "2026-07-10")

        capability = self.provider.get_provider_capabilities()[0]
        snapshots = self.provider.get_raw_snapshots("600519", "2026-07-10")
        interfaces = {item.interface for item in snapshots}

        self.assertTrue(capability.supports("dragon_tiger"))
        self.assertTrue(capability.supports("margin_financing"))
        self.assertTrue({"top_list", "top_inst", "margin_detail"}.issubset(interfaces))
        self.assertTrue(all(item.content_sha256 for item in snapshots))
        self.assertTrue(all(item.status == "passed" for item in self.provider.get_data_quality_reports("600519", "2026-07-10")))

    def test_core_provider_methods_do_not_use_sample_data(self) -> None:
        self.assertEqual(self.provider.get_stock_profile("600519").name, "测试股份")
        self.assertEqual(self.provider.get_daily_prices("600519", "2026-07-10", 30)[-1].turnover_rate, 3.2)
        self.assertEqual(self.provider.get_money_flow("600519", "2026-07-10").northbound_signal, "北向持股增加")
        self.assertEqual(self.provider.get_money_flow("600519", "2026-07-10").large_net_inflow, 300_000)
        self.assertGreaterEqual(len(self.provider.get_evidence_sources("600519", "2026-07-10")), 5)

    def test_fundamentals_fill_same_period_peer_medians_with_provenance(self) -> None:
        snapshot = self.provider.get_fundamentals("600519", "2026-07-10")

        self.assertEqual(snapshot.peer_as_of, "2026-03-31")
        self.assertEqual(snapshot.peer_medians["roe"], 8)
        self.assertEqual(snapshot.peer_medians["gross_margin"], 30)
        self.assertEqual(snapshot.peer_medians["debt_to_asset"], 40)
        self.assertEqual(snapshot.peer_sample_sizes["roe"], 3)
        self.assertEqual(snapshot.peer_source_id, "peer-fund-001")
        source = next(
            item
            for item in self.provider.get_evidence_sources("600519", "2026-07-10")
            if item.id == "peer-fund-001"
        )
        self.assertTrue(source.snapshot_ids)
        quality = next(
            item
            for item in self.provider.get_data_quality_reports("600519", "2026-07-10")
            if item.dataset == "fundamental_peers"
        )
        self.assertEqual(quality.status, "passed")

    def test_capital_flow_history_is_dated_and_quality_checked(self) -> None:
        history = self.provider.get_capital_flow_history("600519", "2026-07-10")

        self.assertEqual(len(history), 5)
        self.assertEqual(history[-1].main_net_inflow, 500_000)
        self.assertEqual(history[-1].margin_balance, 1000)
        self.assertEqual(history[-1].northbound_holding_change, 25)
        self.assertEqual(
            set(history[-1].source_ids),
            {"flow-history-001", "margin-history-001", "northbound-history-001"},
        )
        quality = next(
            item
            for item in self.provider.get_data_quality_reports("600519", "2026-07-10")
            if item.dataset == "capital_flow_history"
        )
        self.assertEqual(quality.status, "passed")
        self.assertTrue(quality.snapshot_ids)

    def test_dragon_tiger_history_keeps_seat_amounts_and_provenance(self) -> None:
        history = self.provider.get_dragon_tiger_history("600519", "2026-07-10")

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].seat_name, "机构专用")
        self.assertEqual(history[0].side, "buy")
        self.assertEqual(history[0].net_buy_amount, 50)
        quality = next(
            item for item in self.provider.get_data_quality_reports("600519", "2026-07-10")
            if item.dataset == "dragon_tiger_history"
        )
        self.assertEqual(quality.status, "passed")
        self.assertTrue(quality.snapshot_ids)

    def test_earnings_forecast_and_express_keep_comparable_yuan_values(self) -> None:
        items = self.provider.get_announcements("600519", "2026-07-10")
        forecast = next(item for item in items if item.event_type == "earnings_forecast")
        express = next(item for item in items if item.event_type == "earnings_express")

        self.assertEqual(forecast.forecast_net_profit_min_yuan, 1_000_000)
        self.assertEqual(forecast.forecast_net_profit_max_yuan, 1_200_000)
        self.assertEqual(express.actual_net_profit_yuan, 1_300_000)
        self.assertEqual(forecast.report_period, express.report_period)

    def test_insufficient_peer_sample_does_not_invent_medians(self) -> None:
        class SparseIndustryTushare(FakeTushare):
            def stock_basic(self, **kwargs):
                if "ts_code" in kwargs:
                    return super().stock_basic(**kwargs)
                return [
                    {"ts_code": "600519.SH", "industry": "电子", "list_status": "L"},
                    {"ts_code": "600001.SH", "industry": "电子", "list_status": "L"},
                ]

        provider = TushareMarketDataProvider(pro_client=SparseIndustryTushare())
        snapshot = provider.get_fundamentals("600519", "2026-07-10")

        self.assertEqual(snapshot.peer_medians, {})
        self.assertIsNone(snapshot.peer_source_id)
        self.assertTrue(snapshot.peer_unavailable_reasons)
        quality = next(
            item
            for item in provider.get_data_quality_reports("600519", "2026-07-10")
            if item.dataset == "fundamental_peers"
        )
        self.assertEqual(quality.status, "failed")

    def test_convertible_bond_snapshot_uses_official_units_and_sources(self) -> None:
        snapshot = self.provider.get_convertible_bond_snapshot("123001", "2026-07-10")
        self.assertEqual(snapshot.symbol, "123001.SZ")
        self.assertEqual(snapshot.remaining_balance, 200_000_000)
        self.assertEqual(snapshot.amount, 50_000_000)
        self.assertIn("cb-daily-001", snapshot.source_ids)

    def test_market_context_uses_market_wide_data_and_dynamic_sentiment(self) -> None:
        context = self.provider.get_market_context("2026-07-10")

        self.assertEqual(context.data_status, "verified")
        self.assertEqual(context.as_of, "2026-07-10")
        self.assertEqual(context.advancers, 3)
        self.assertEqual(context.decliners, 1)
        self.assertEqual(context.limit_up_count, 3)
        self.assertEqual(context.limit_down_count, 0)
        self.assertEqual(context.sealed_limit_up_rate, 100.0)
        self.assertEqual(context.failed_breakout_rate, 0.0)
        self.assertEqual(context.one_price_limit_up_count, 1)
        self.assertEqual(context.board_ladder, {"1板": 0, "2板": 0, "3板": 1, "4板以上": 2})
        self.assertEqual(len(context.sentiment_history), 5)
        self.assertNotEqual(context.hot_money_cycle, "数据不足")
        dynamics = analyze_sentiment_dynamics(context)
        self.assertIsNotNone(dynamics.velocity)
        self.assertIsNotNone(dynamics.acceleration)
        self.assertEqual(dynamics.observations, 5)
        self.assertIn("人工智能", context.policy_themes)
        market_source = next(item for item in self.provider.get_evidence_sources("600519", "2026-07-10") if item.id == "market-001")
        self.assertTrue(market_source.snapshot_ids)
        quality = next(item for item in self.provider.get_data_quality_reports("600519", "2026-07-10") if item.dataset == "market_sentiment")
        self.assertEqual(quality.status, "passed")

    def test_ah_premium_uses_official_aligned_comparison(self) -> None:
        class AhTushare(FakeTushare):
            def stk_ah_comparison(self, **kwargs):
                return [{
                    "hk_code": "03968.HK",
                    "ts_code": "600036.SH",
                    "trade_date": "20260710",
                    "hk_close": 41.2,
                    "close": 45.8,
                    "ah_comparison": 1.21,
                    "ah_premium": 21.4,
                }]

        provider = TushareMarketDataProvider(pro_client=AhTushare())
        snapshot = provider.get_ah_premium("600036", "2026-07-10")

        self.assertEqual(snapshot.data_status, "verified")
        self.assertEqual(snapshot.h_symbol, "03968.HK")
        self.assertEqual(snapshot.ah_premium_pct, 21.4)
        source = next(item for item in provider.get_evidence_sources("600036", "2026-07-10") if item.id == "ah-premium-001")
        self.assertTrue(source.snapshot_ids)
        quality = next(item for item in provider.get_data_quality_reports("600036", "2026-07-10") if item.dataset == "ah_premium")
        self.assertEqual(quality.status, "passed")

    def test_non_ah_stock_is_explicitly_not_applicable(self) -> None:
        snapshot = self.provider.get_ah_premium("600519", "2026-07-10")
        self.assertEqual(snapshot.data_status, "not_applicable")
        self.assertIsNone(snapshot.ah_premium_pct)

    def test_ah_premium_rejects_source_dates_before_official_coverage(self) -> None:
        snapshot = self.provider.get_ah_premium("600036", "2025-08-11")

        self.assertEqual(snapshot.data_status, "unavailable")
        self.assertTrue(any("coverage starts" in reason for reason in snapshot.unavailable_reasons))

    def test_ah_premium_rejects_symbol_or_ratio_semantic_mismatch(self) -> None:
        class InvalidAhTushare(FakeTushare):
            def stk_ah_comparison(self, **kwargs):
                return [{
                    "hk_code": "03968.HK",
                    "ts_code": "600000.SH",
                    "trade_date": "20260710",
                    "hk_close": 41.2,
                    "close": 45.8,
                    "ah_comparison": 1.10,
                    "ah_premium": 35.0,
                }]

        provider = TushareMarketDataProvider(pro_client=InvalidAhTushare())
        snapshot = provider.get_ah_premium("600036", "2026-07-10")

        self.assertEqual(snapshot.data_status, "unavailable")
        self.assertFalse(any(item.id == "ah-premium-001" for item in provider.get_evidence_sources("600036", "2026-07-10")))
        quality = next(
            item
            for item in provider.get_data_quality_reports("600036", "2026-07-10")
            if item.dataset == "ah_premium"
        )
        self.assertEqual(quality.status, "failed")
        self.assertIn("ah_symbol_mismatch", {item.code for item in quality.issues})
        self.assertIn("inconsistent_ah_comparison", {item.code for item in quality.issues})

    def test_failed_limit_pool_is_not_relabelled_as_zero(self) -> None:
        class MissingLimitPoolTushare(FakeTushare):
            def limit_list_d(self, **kwargs):
                raise RuntimeError("entitlement unavailable")

        provider = TushareMarketDataProvider(pro_client=MissingLimitPoolTushare())
        context = provider.get_market_context("2026-07-10")

        self.assertEqual(context.data_status, "insufficient")
        self.assertIsNone(context.limit_up_count)
        self.assertIsNone(context.limit_down_count)
        self.assertEqual(context.hot_money_cycle, "数据不足")
        self.assertFalse(any(item.id == "market-001" for item in provider.get_evidence_sources("600519", "2026-07-10")))
        quality = next(item for item in provider.get_data_quality_reports("600519", "2026-07-10") if item.dataset == "market_sentiment")
        self.assertEqual(quality.status, "failed")
        self.assertTrue(quality.blocking)

    def test_incomplete_market_rows_are_rejected_before_breadth_scoring(self) -> None:
        class IncompleteMarketTushare(FakeTushare):
            def daily(self, **kwargs):
                rows = super().daily(**kwargs)
                if "ts_code" not in kwargs and kwargs["trade_date"] == "20260710":
                    rows[0] = {key: value for key, value in rows[0].items() if key != "amount"}
                return rows

        provider = TushareMarketDataProvider(pro_client=IncompleteMarketTushare())
        context = provider.get_market_context("2026-07-10")

        self.assertEqual(context.data_status, "insufficient")
        self.assertIsNone(context.advancers)
        self.assertTrue(any("缺失字段或重复代码" in reason for reason in context.unavailable_reasons))

    def test_missing_money_and_margin_data_are_not_relabelled_as_zero(self) -> None:
        class MissingFlowTushare(FakeTushare):
            def moneyflow(self, **kwargs):
                return []

            def margin_detail(self, **kwargs):
                return []

            def hk_hold(self, **kwargs):
                return []

        provider = TushareMarketDataProvider(pro_client=MissingFlowTushare())
        flow = provider.get_money_flow("600519", "2026-07-10")
        finding = analyze_capital_flow(flow, provider.get_market_signals("600519", "2026-07-10"))
        history = provider.get_capital_flow_history("600519", "2026-07-10")

        self.assertIsNone(flow.main_net_inflow)
        self.assertIsNone(flow.super_large_net_inflow)
        self.assertIsNone(flow.margin_balance_change)
        self.assertIn("数据不足", finding.conclusion)
        self.assertEqual(finding.confidence, 0.0)
        self.assertEqual(history, [])
        history_quality = next(
            item
            for item in provider.get_data_quality_reports("600519", "2026-07-10")
            if item.dataset == "capital_flow_history"
        )
        self.assertEqual(history_quality.status, "failed")

    def test_single_northbound_disclosure_does_not_invent_holding_change(self) -> None:
        class SingleDisclosureTushare(FakeTushare):
            def hk_hold(self, **kwargs):
                return [{"trade_date": "20260710", "vol": 570}]

        provider = TushareMarketDataProvider(pro_client=SingleDisclosureTushare())
        signals = provider.get_market_signals("600519", "2026-07-10")
        history = provider.get_capital_flow_history("600519", "2026-07-10")

        self.assertIsNone(signals.northbound_holding)
        self.assertTrue(all(item.northbound_holding_change is None for item in history))
        self.assertFalse(any("northbound-history-001" in item.source_ids for item in history))


if __name__ == "__main__":
    unittest.main()
