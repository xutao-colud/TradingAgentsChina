from __future__ import annotations

import unittest

from app.reporting.citations import (
    model_friendly_evidence,
    public_evidence_citation,
    public_source_type,
    sanitize_model_interpretation,
)
from app.schemas.report import EvidenceSource


class PublicCitationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.price = EvidenceSource(
            id="price-001",
            title="日线与估值快照",
            source_type="akshare",
            as_of="2026-07-24",
        )
        self.announcement = EvidenceSource(
            id="announcement-cninfo-85619be4113ae",
            title="股份回购进展公告",
            source_type="cninfo",
            as_of="2026-07-21",
        )

    def test_public_citation_explains_evidence_provider_and_date(self) -> None:
        citation = public_evidence_citation(self.price)

        self.assertEqual(citation, "【日线与估值快照｜AkShare 数据接口｜数据截至 2026-07-24】")
        self.assertEqual(
            public_source_type("verified_cache:eastmoney_push2"),
            "本地已核验缓存（原始来源：东方财富公开数据）",
        )

    def test_internal_source_syntax_is_replaced_in_model_text(self) -> None:
        content = (
            "趋势验证（source id: price-001, as_of: 2026-07-24）仍偏弱。\n"
            "公告核验（如 source id: announcement-cninfo-85619be4113ae, as_of: 2026-07-21）形成反证。"
        )

        rendered = sanitize_model_interpretation(content, [self.price, self.announcement])

        self.assertNotIn("source id", rendered)
        self.assertNotIn("as_of", rendered)
        self.assertIn("【日线与估值快照｜AkShare 数据接口｜数据截至 2026-07-24】", rendered)
        self.assertIn("【股份回购进展公告｜巨潮资讯｜数据截至 2026-07-21】", rendered)

    def test_unknown_internal_source_is_not_exposed(self) -> None:
        rendered = sanitize_model_interpretation(
            "待核验（source_id: missing-001, as_of: 2026-07-24）",
            [],
        )

        self.assertEqual(rendered, "待核验【待核验证据】")

    def test_model_evidence_packet_uses_citations_instead_of_ids(self) -> None:
        rendered = model_friendly_evidence(
            {
                "source_ids": ["price-001"],
                "as_of": "2026-07-24",
                "gap": "缺少 price-001 与 unavailable-001。",
                "source": {
                    "id": "price-001",
                    "title": self.price.title,
                    "source_type": self.price.source_type,
                    "as_of": self.price.as_of,
                },
            },
            {"price-001": self.price},
        )

        self.assertNotIn("source_ids", rendered)
        self.assertNotIn("as_of", rendered)
        self.assertNotIn("price-001", rendered["gap"])
        self.assertNotIn("unavailable-001", rendered["gap"])
        self.assertIn("待核验证据", rendered["gap"])
        self.assertNotIn("id", rendered["source"])
        self.assertEqual(rendered["source_citations"], [public_evidence_citation(self.price)])


if __name__ == "__main__":
    unittest.main()
