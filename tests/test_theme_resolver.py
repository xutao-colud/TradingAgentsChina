from __future__ import annotations

import unittest

from app.knowledge.theme_resolver import resolve_themes
from app.schemas.report import StockProfile


class ThemeResolverTest(unittest.TestCase):
    def test_provider_concept_precedes_configured_industry_default(self) -> None:
        profile = StockProfile("300001.SZ", "测试", "半导体", "chinext", concepts=["AI"])
        matches = resolve_themes(profile, ["人工智能", "半导体国产替代"])

        by_theme = {item.theme: item for item in matches}
        self.assertEqual(by_theme["人工智能"].source, "provider_concept")
        self.assertEqual(by_theme["半导体国产替代"].source, "configured_industry_default")

    def test_unmatched_theme_is_not_created_from_a_generic_label(self) -> None:
        profile = StockProfile("600001.SH", "测试", "银行", "main")
        self.assertEqual(resolve_themes(profile, ["机器人"]), [])


if __name__ == "__main__":
    unittest.main()
