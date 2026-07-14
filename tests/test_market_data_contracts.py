from __future__ import annotations

import unittest

from app.schemas.report import (
    AshareMarketSignals,
    CorporateEvent,
    DragonTigerRecord,
    EvidenceSource,
    MarginFinancingRecord,
    NorthboundHoldingRecord,
)


class MarketDataContractsTest(unittest.TestCase):
    def test_extended_signals_keep_provenance_and_time(self) -> None:
        signals = AshareMarketSignals(
            data_status="verified",
            dragon_tiger=[DragonTigerRecord("2026-07-10", "日涨幅偏离", 1_000_000, 500_000, source_id="lhb-001")],
            margin_financing=MarginFinancingRecord("2026-07-10", 20_000_000, 1_000_000, 5_000_000, 3_000_000, "margin-001"),
            northbound_holding=NorthboundHoldingRecord("2026-07-10", 10_000, 100_000, 500, "north-001"),
            corporate_events=[CorporateEvent("forecast", "业绩预告", "2026-07-09", "negative", "利润预减", "event-001")],
            evidence_sources=[EvidenceSource("lhb-001", "龙虎榜", "tushare_top_list", "2026-07-10")],
        )

        self.assertEqual(signals.dragon_tiger[0].source_id, "lhb-001")
        self.assertEqual(signals.margin_financing.trade_date, "2026-07-10")
        self.assertEqual(signals.corporate_events[0].impact, "negative")
        self.assertEqual(signals.evidence_sources[0].as_of, "2026-07-10")


if __name__ == "__main__":
    unittest.main()
