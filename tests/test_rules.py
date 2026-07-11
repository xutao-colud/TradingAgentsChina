import unittest

from app.rules.trading_rules import daily_limit_pct, invalid_conditions, normalize_symbol
from app.schemas.report import DailyPrice, StockProfile


class TradingRulesTest(unittest.TestCase):
    def test_normalize_symbol_adds_expected_exchange(self) -> None:
        self.assertEqual(normalize_symbol("600519"), "600519.SH")
        self.assertEqual(normalize_symbol("000001"), "000001.SZ")
        self.assertEqual(normalize_symbol("300750"), "300750.SZ")
        self.assertEqual(normalize_symbol("688981"), "688981.SH")

    def test_daily_limit_pct_by_board_and_st_flag(self) -> None:
        self.assertEqual(daily_limit_pct(StockProfile("600519.SH", "贵州茅台", "白酒", "main")), 10)
        self.assertEqual(daily_limit_pct(StockProfile("300750.SZ", "宁德时代", "电池", "chinext")), 20)
        self.assertEqual(daily_limit_pct(StockProfile("688981.SH", "中芯国际", "半导体", "star")), 20)
        self.assertEqual(daily_limit_pct(StockProfile("430047.BJ", "样例", "样例", "beijing")), 30)
        self.assertEqual(daily_limit_pct(StockProfile("600000.SH", "ST样例", "样例", "main", is_st=True)), 5)

    def test_invalid_conditions_catches_liquidity_and_status(self) -> None:
        profile = StockProfile("600000.SH", "ST样例", "样例", "main", is_st=True, is_suspended=True)
        prices = [
            DailyPrice("2026-07-10", 10, 10.2, 9.8, 10.1, 1000, 12_000_000, 0.1),
        ]
        conditions = invalid_conditions(profile, prices)
        self.assertEqual(len(conditions), 4)
        self.assertTrue(any("停牌" in item for item in conditions))
        self.assertTrue(any("ST" in item for item in conditions))
        self.assertTrue(any("流动性不足" in item for item in conditions))
        self.assertTrue(any("换手率偏低" in item for item in conditions))


if __name__ == "__main__":
    unittest.main()

