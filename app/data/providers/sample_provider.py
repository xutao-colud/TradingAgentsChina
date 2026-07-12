from __future__ import annotations

from datetime import date, datetime, timedelta

from app.data.providers.base import MarketDataProvider
from app.rules.trading_rules import normalize_symbol
from app.schemas.report import (
    Announcement,
    DailyPrice,
    EvidenceSource,
    FundamentalSnapshot,
    MarketContext,
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

    def get_fundamentals(self, symbol: str) -> FundamentalSnapshot:
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
            )
        if normalized == "300750.SZ":
            return FundamentalSnapshot(12.8, 9.5, 20.3, 23.8, 58.0, 24.5, 4.1, 0.68, "一致预期稳定")
        if normalized == "688981.SH":
            return FundamentalSnapshot(18.1, 21.0, 9.8, 39.5, 33.0, 55.0, 3.8, 0.61, "景气预期改善")
        return FundamentalSnapshot(6.0, 4.0, 8.0, 25.0, 45.0, 22.0, 1.8, 0.55, "暂无明显变化")

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
        )

    def get_evidence_sources(self, symbol: str, analysis_date: str) -> list[EvidenceSource]:
        normalized = normalize_symbol(symbol)
        sources = [
            EvidenceSource("price-001", f"{normalized} 样例日线行情", "offline_sample", analysis_date),
            EvidenceSource("fund-001", f"{normalized} 样例财务快照", "offline_sample", analysis_date),
            EvidenceSource("flow-001", f"{normalized} 样例资金流", "offline_sample", analysis_date),
            EvidenceSource("market-001", "A股市场宽度样例", "offline_sample", analysis_date),
            EvidenceSource("ann-001", f"{normalized} 样例公司公告", "offline_sample", analysis_date),
        ]
        if normalized == "600519.SH":
            sources.append(EvidenceSource("ann-002", f"{normalized} 样例经营数据披露", "offline_sample", analysis_date))
        return sources


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
