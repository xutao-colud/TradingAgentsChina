from __future__ import annotations

from datetime import date, datetime, timedelta

from app.data.providers.base import MarketDataProvider
from app.rules.trading_rules import normalize_symbol
from app.schemas.report import (
    Announcement,
    AshareMarketSignals,
    CapitalFlowObservation,
    DailyPrice,
    DragonTigerRecord,
    EvidenceSource,
    FundamentalSnapshot,
    IndustryChainNode,
    IndustryContext,
    IndustryFlowObservation,
    IndustryValuationObservation,
    MarketContext,
    MarketSentimentObservation,
    MoneyFlowSnapshot,
    StockProfile,
)

KNOWN_STOCK_PROFILES: dict[str, StockProfile] = {
    "000725.SZ": StockProfile(symbol="000725.SZ", name="京东方A", industry="显示面板", board="main"),
    "300750.SZ": StockProfile(symbol="300750.SZ", name="宁德时代", industry="电池", board="chinext"),
    "600519.SH": StockProfile(symbol="600519.SH", name="贵州茅台", industry="白酒", board="main"),
    "688981.SH": StockProfile(symbol="688981.SH", name="中芯国际", industry="半导体", board="star"),
}


class SampleMarketDataProvider(MarketDataProvider):
    """Offline fixture provider used by tests, demos, and local-first workflows."""

    def get_stock_profile(self, symbol: str) -> StockProfile:
        normalized = normalize_symbol(symbol)
        if normalized in KNOWN_STOCK_PROFILES:
            return KNOWN_STOCK_PROFILES[normalized]
        return StockProfile(symbol=normalized, name="样例股份", industry="样例", board="main")

    def get_daily_prices(self, symbol: str, analysis_date: str, lookback_days: int) -> list[DailyPrice]:
        normalized = normalize_symbol(symbol)
        days = max(2, lookback_days)
        end = _parse_date(analysis_date)
        dates = [(end - timedelta(days=days - index - 1)).isoformat() for index in range(days)]
        if normalized == "600519.SH":
            return _build_price_series(dates, base=1492.0, daily_step=1.9, volume_base=3_250_000, amount_scale=1_520.0)
        if normalized == "300750.SZ":
            return _build_price_series(dates, base=188.0, daily_step=0.7, volume_base=38_000_000, amount_scale=195.0)
        if normalized == "688981.SH":
            return _build_price_series(dates, base=74.0, daily_step=0.35, volume_base=72_000_000, amount_scale=78.0)
        return _build_price_series(dates, base=12.0, daily_step=0.05, volume_base=16_000_000, amount_scale=12.5)

    def get_fundamentals(self, symbol: str, analysis_date: str | None = None) -> FundamentalSnapshot:
        normalized = normalize_symbol(symbol)
        if normalized == "600519.SH":
            return FundamentalSnapshot(
                revenue_growth_yoy=15.2,
                profit_growth_yoy=18.6,
                roe=31.5,
                gross_margin=91.7,
                debt_to_asset=22.4,
                pe_ttm=28.6,
                pb=9.3,
                cashflow_quality=0.88,
                forecast_revision="一致预期小幅上修",
                peer_medians={"revenue_growth_yoy": 10.0, "profit_growth_yoy": 12.0},
                peer_sample_sizes={"revenue_growth_yoy": 12, "profit_growth_yoy": 12},
                peer_as_of=analysis_date,
                peer_source_id="peer-fund-001",
            )
        if normalized == "300750.SZ":
            return FundamentalSnapshot(12.8, 9.5, 20.3, 23.8, 58.0, 24.5, 4.1, 0.68, "一致预期稳定", peer_medians={"revenue_growth_yoy": 8.0, "profit_growth_yoy": 7.0}, peer_sample_sizes={"revenue_growth_yoy": 12, "profit_growth_yoy": 12}, peer_as_of=analysis_date, peer_source_id="peer-fund-001")
        if normalized == "688981.SH":
            return FundamentalSnapshot(18.1, 21.0, 9.8, 39.5, 33.0, 55.0, 3.8, 0.61, "景气预期改善", peer_medians={"revenue_growth_yoy": 12.0, "profit_growth_yoy": 15.0}, peer_sample_sizes={"revenue_growth_yoy": 12, "profit_growth_yoy": 12}, peer_as_of=analysis_date, peer_source_id="peer-fund-001")
        return FundamentalSnapshot(6.0, 4.0, 8.0, 25.0, 45.0, 22.0, 1.8, 0.55, "暂无明显变化", peer_medians={"revenue_growth_yoy": 5.0, "profit_growth_yoy": 4.0}, peer_sample_sizes={"revenue_growth_yoy": 12, "profit_growth_yoy": 12}, peer_as_of=analysis_date, peer_source_id="peer-fund-001")

    def get_money_flow(self, symbol: str, analysis_date: str) -> MoneyFlowSnapshot:
        normalized = normalize_symbol(symbol)
        if normalized == "600519.SH":
            return MoneyFlowSnapshot(
                main_net_inflow=82_000_000,
                super_large_net_inflow=42_000_000,
                margin_balance_change=0.6,
                northbound_signal="连续温和流入",
                turnover_rate=0.82,
                block_trade_signal="无异常折价大宗交易",
            )
        if normalized == "300750.SZ":
            return MoneyFlowSnapshot(56_000_000, 21_000_000, 0.2, "小幅流入", 1.7, "少量平价成交")
        if normalized == "688981.SH":
            return MoneyFlowSnapshot(38_000_000, 18_000_000, 0.4, "行业偏好改善", 2.9, "无明显异常")
        return MoneyFlowSnapshot(8_000_000, 2_000_000, -0.1, "暂无明显信号", 1.5, "无明显异常")

    def get_industry_context(self, symbol: str, analysis_date: str) -> IndustryContext:
        industry = self.get_stock_profile(symbol).industry
        flow_names = [f"{industry}上游样例", industry, f"{industry}下游样例", "市场其他行业样例"]
        flows = [
            IndustryFlowObservation(
                trade_date=analysis_date,
                industry=name,
                industry_code=f"SAMPLE-{index}",
                net_amount=amount,
                pct_change=change,
                company_count=20 + index,
                source_id="industry-flow-001",
            )
            for index, (name, amount, change) in enumerate(zip(
                flow_names,
                (220_000_000, 360_000_000, 140_000_000, -180_000_000),
                (1.2, 1.8, 0.7, -0.8),
            ), start=1)
        ]
        end = _parse_date(analysis_date)
        valuations = [
            IndustryValuationObservation(
                trade_date=(end - timedelta(days=(5 - index) * 30)).isoformat(),
                pe_ttm_median=18.0 + index,
                pb_median=2.0 + index * 0.1,
                sample_size=12,
                source_ids=["industry-valuation-001"],
            )
            for index in range(6)
        ]
        return IndustryContext(
            data_status="sample",
            industry=industry,
            as_of=analysis_date,
            flow_observations=flows,
            valuation_history=valuations,
            chain_nodes=[
                IndustryChainNode("upstream", flow_names[0], "industry-chain-001"),
                IndustryChainNode("midstream", industry, "industry-chain-001"),
                IndustryChainNode("downstream", flow_names[2], "industry-chain-001"),
            ],
            source_ids=["industry-flow-001", "industry-valuation-001", "industry-chain-001"],
        )

    def get_capital_flow_history(self, symbol: str, analysis_date: str) -> list[CapitalFlowObservation]:
        end = _parse_date(analysis_date)
        dates = [(end - timedelta(days=9 - index)).isoformat() for index in range(10)]
        return [
            CapitalFlowObservation(
                trade_date=trade_date,
                main_net_inflow=4_000_000 + index * 500_000,
                northbound_holding_change=100_000 + index * 10_000,
                margin_balance=1_000_000_000 + index * 5_000_000,
                source_ids=["flow-history-001", "margin-history-001", "northbound-history-001"],
            )
            for index, trade_date in enumerate(dates)
        ]

    def get_announcements(self, symbol: str, analysis_date: str) -> list[Announcement]:
        normalized = normalize_symbol(symbol)
        if normalized == "600519.SH":
            return [
                Announcement(
                    title="年度权益分派实施公告",
                    published_at=analysis_date,
                    priority="company",
                    sentiment="positive",
                    summary="现金分红延续，股东回报稳定。",
                    source_id="ann-001",
                ),
                Announcement(
                    title="经营数据自愿披露",
                    published_at=analysis_date,
                    priority="company",
                    sentiment="neutral",
                    summary="渠道库存和批价仍需后续跟踪。",
                    source_id="ann-002",
                ),
            ]
        return [
            Announcement(
                title="样例公告",
                published_at=analysis_date,
                priority="company",
                sentiment="neutral",
                summary="暂无重大影响事项。",
                source_id="ann-001",
            )
        ]

    def get_market_context(self, analysis_date: str) -> MarketContext:
        return MarketContext(
            index_name="沪深300",
            index_change_pct=0.72,
            total_amount=932_000_000_000,
            advancers=3270,
            decliners=1740,
            limit_up_count=72,
            limit_down_count=8,
            hot_money_cycle="震荡修复",
            policy_themes=["消费复苏", "高股息", "国企改革", "人工智能"],
            failed_breakout_rate=18.0,
            yesterday_limit_up_premium=2.4,
            max_consecutive_boards=5,
            first_board_count=41,
            second_board_success_rate=36.0,
            strong_stock_return=3.8,
            sealed_limit_up_rate=82.0,
            one_price_limit_up_count=6,
            broken_limit_up_count=16,
            board_ladder={"1板": 41, "2板": 18, "3板": 8, "4板以上": 5},
            sentiment_history=[
                MarketSentimentObservation("2026-07-08", 38, 16, 29.0, 0.6, 3, 24, 26.0, 1.2, sealed_limit_up_rate=71.0, one_price_limit_up_count=2, broken_limit_up_count=16, board_ladder={"1板": 24, "2板": 8, "3板": 4, "4板以上": 2}),
                MarketSentimentObservation("2026-07-09", 55, 12, 23.0, 1.4, 4, 33, 31.0, 2.1, sealed_limit_up_rate=77.0, one_price_limit_up_count=4, broken_limit_up_count=16, board_ladder={"1板": 33, "2板": 12, "3板": 7, "4板以上": 3}),
                MarketSentimentObservation("2026-07-10", 72, 8, 18.0, 2.4, 5, 41, 36.0, 3.8, sealed_limit_up_rate=82.0, one_price_limit_up_count=6, broken_limit_up_count=16, board_ladder={"1板": 41, "2板": 18, "3板": 8, "4板以上": 5}),
            ],
        )

    def get_evidence_sources(self, symbol: str, analysis_date: str) -> list[EvidenceSource]:
        normalized = normalize_symbol(symbol)
        sources = [
            EvidenceSource("profile-001", f"{normalized} 样例证券基础信息", "offline_sample", analysis_date),
            EvidenceSource("price-001", f"{normalized} 样例日线行情", "offline_sample", analysis_date),
            EvidenceSource("fund-001", f"{normalized} 样例财务快照", "offline_sample", analysis_date),
            EvidenceSource("peer-fund-001", f"{normalized} 样例同行财务中位数", "offline_sample", analysis_date),
            EvidenceSource("flow-001", f"{normalized} 样例资金流", "offline_sample", analysis_date),
            EvidenceSource("flow-history-001", f"{normalized} 样例主力资金历史", "offline_sample", analysis_date),
            EvidenceSource("margin-history-001", f"{normalized} 样例融资余额历史", "offline_sample", analysis_date),
            EvidenceSource("northbound-history-001", f"{normalized} 样例北向变化历史", "offline_sample", analysis_date),
            EvidenceSource("market-001", "A股市场宽度样例", "offline_sample", analysis_date),
            EvidenceSource("industry-flow-001", f"{normalized} 样例行业资金横截面", "offline_sample", analysis_date),
            EvidenceSource("industry-valuation-001", f"{normalized} 样例行业估值历史", "offline_sample", analysis_date),
            EvidenceSource("industry-chain-001", f"{normalized} 样例产业链分类", "offline_sample", analysis_date),
            EvidenceSource("ann-001", f"{normalized} 样例公司公告", "offline_sample", analysis_date),
        ]
        if normalized == "600519.SH":
            sources.append(EvidenceSource("ann-002", f"{normalized} 样例经营数据披露", "offline_sample", analysis_date))
        return sources

    def get_market_signals(self, symbol: str, analysis_date: str) -> AshareMarketSignals:
        normalized = normalize_symbol(symbol)
        source = EvidenceSource("dragon-tiger-001", f"{normalized} 样例龙虎榜", "offline_sample", analysis_date)
        return AshareMarketSignals(
            data_status="sample",
            dragon_tiger=[DragonTigerRecord(analysis_date, "样例上榜原因", 0.0, None, source_id="dragon-tiger-001")],
            evidence_sources=[source],
        )


def _build_price_series(
    dates: list[str],
    base: float,
    daily_step: float,
    volume_base: float,
    amount_scale: float,
) -> list[DailyPrice]:
    prices: list[DailyPrice] = []
    for index, trade_date in enumerate(dates):
        wave = ((index % 5) - 2) * 0.45
        close = round(base + index * daily_step + wave, 2)
        open_price = round(close - 1.6 + (index % 3) * 0.4, 2)
        high = round(max(open_price, close) + 3.2, 2)
        low = round(min(open_price, close) - 2.8, 2)
        volume = volume_base + index * volume_base * 0.012 + (index % 4) * volume_base * 0.025
        amount = volume * amount_scale
        turnover = 0.55 + (index % 6) * 0.08
        prices.append(
            DailyPrice(
                trade_date=trade_date,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=round(volume, 2),
                amount=round(amount, 2),
                turnover_rate=round(turnover, 2),
            )
        )
    return prices


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return date.today()
