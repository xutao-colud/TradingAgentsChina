from __future__ import annotations

import unittest

from app.schemas.report import Announcement, DailyPrice
from app.skills.announcement_impact import analyze_announcement_impact


def _price(day: int, open_price: float, close: float) -> DailyPrice:
    return DailyPrice(f"2026-07-{day:02d}", open_price, max(open_price, close), min(open_price, close), close, 100, 1000, 1)


class AnnouncementImpactTest(unittest.TestCase):
    def test_detects_high_open_fade_from_next_trading_day(self) -> None:
        item = Announcement("重大事项公告", "2026-07-01", "company", "positive", "测试", "ann-001")
        prices = [_price(1, 10, 10), _price(2, 12, 10.5), _price(3, 10.5, 10.4)]

        insight = analyze_announcement_impact([item], prices, "2026-07-03")

        reaction = insight.details["market_reactions"][0]
        self.assertEqual(reaction["pattern"], "high_open_fade")
        self.assertEqual(reaction["reaction_date"], "2026-07-02")
        self.assertEqual(insight.stage, "利好兑现分歧")

    def test_forecast_revision_and_express_are_compared_in_same_period_and_unit(self) -> None:
        items = [
            Announcement(
                "首次业绩预告", "2026-06-01", "company", "positive", "", "forecast-1",
                event_type="earnings_forecast", report_period="2026-06-30",
                forecast_net_profit_min_yuan=1_000_000, forecast_net_profit_max_yuan=1_200_000,
            ),
            Announcement(
                "修正业绩预告", "2026-06-20", "company", "positive", "", "forecast-2",
                event_type="earnings_forecast", report_period="2026-06-30",
                forecast_net_profit_min_yuan=1_300_000, forecast_net_profit_max_yuan=1_500_000,
            ),
            Announcement(
                "业绩快报", "2026-07-01", "company", "neutral", "", "express-1",
                event_type="earnings_express", report_period="2026-06-30", actual_net_profit_yuan=1_600_000,
            ),
        ]

        insight = analyze_announcement_impact(items, [], "2026-07-01")

        check = insight.details["forecast_checks"][0]
        self.assertEqual(check["forecast_revision"], "up")
        self.assertEqual(check["actual_vs_forecast"], "above")

    def test_inquiry_reply_is_linked_observationally_and_unanswered_remains_risk(self) -> None:
        answered = Announcement(
            "2025年年度报告财务事项问询函", "2026-06-01", "exchange", "negative", "", "inquiry-1", event_type="inquiry",
        )
        reply = Announcement(
            "2025年年度报告财务事项问询函回复", "2026-06-10", "exchange", "neutral", "", "reply-1", event_type="inquiry_reply",
        )
        unanswered = Announcement(
            "重大资产重组事项关注函", "2026-06-20", "exchange", "negative", "", "inquiry-2", event_type="inquiry",
        )

        insight = analyze_announcement_impact([answered, reply, unanswered], [], "2026-07-01")

        statuses = {item["source_id"]: item["status"] for item in insight.details["inquiry_checks"]}
        self.assertEqual(statuses["inquiry-1"], "answered")
        self.assertEqual(statuses["inquiry-2"], "unanswered")
        self.assertEqual(insight.stage, "事件风险待闭环")
        self.assertTrue(any("未匹配到回复" in item for item in insight.risks))

    def test_same_day_announcements_share_one_market_reaction(self) -> None:
        items = [
            Announcement("公告A", "2026-07-01", "company", "positive", "", "ann-a"),
            Announcement("公告B", "2026-07-01", "company", "positive", "", "ann-b"),
        ]
        prices = [_price(1, 10, 10), _price(2, 12, 10.5)]

        insight = analyze_announcement_impact(items, prices, "2026-07-02")

        self.assertEqual(len(insight.details["market_reactions"]), 1)
        self.assertEqual(insight.details["market_reactions"][0]["source_ids"], ["ann-a", "ann-b"])

    def test_realtime_material_drop_is_kept_as_observational_counter_evidence(self) -> None:
        forecast = Announcement(
            "2026年半年度业绩预告",
            "2026-07-09",
            "company",
            "positive",
            "",
            "forecast-1",
            event_type="earnings_forecast",
            report_period="2026-06-30",
            forecast_net_profit_min_yuan=5_000_000_000,
            forecast_net_profit_max_yuan=5_500_000_000,
            published_timestamp="2026-07-09T19:05:00",
            supporting_source_ids=["forecast-detail-1"],
        )
        quote = {
            "price": 6.38,
            "change_pct": -9.12,
            "volume": 30_112_728,
            "amount": 19_757_452_199.2,
            "trade_date": "2026-07-15",
            "trade_time": "2026-07-15T17:19:47",
            "source": "eastmoney_push2delay",
            "data_status": "latest_available",
        }

        insight = analyze_announcement_impact([forecast], [], "2026-07-15", quote)

        self.assertEqual(insight.stage, "公告后显著异动待归因")
        self.assertEqual(insight.details["forecast_coverage"]["status"], "structured")
        self.assertEqual(insight.details["realtime_reaction"]["direction"], "negative")
        self.assertIn("realtime-quote-001", insight.details["source_ids"])
        self.assertTrue(any("不能单独证明" in risk for risk in insight.risks))

    def test_title_only_forecast_is_not_misreported_as_missing_announcement(self) -> None:
        forecast = Announcement(
            "2026年半年度业绩预告",
            "2026-07-09",
            "company",
            "neutral",
            "",
            "forecast-title-1",
            event_type="earnings_forecast",
            report_period="2026-06-30",
        )

        insight = analyze_announcement_impact([forecast], [], "2026-07-15")

        self.assertEqual(insight.details["forecast_coverage"]["status"], "title_only")
        self.assertTrue(any("不得降级表述" in risk for risk in insight.risks))


if __name__ == "__main__":
    unittest.main()
