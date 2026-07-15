from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from app.agents.common import clamp_score
from app.config.runtime import DEFAULT_CONFIG_PATH, clear_runtime_settings_cache, load_runtime_settings
from app.llm.config import DeepSeekConfig
from app.data.providers.tushare_provider import TushareMarketDataProvider


class RuntimeConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_config_path = os.environ.get("TRADINGOS_CONFIG_PATH")
        clear_runtime_settings_cache()

    def tearDown(self) -> None:
        if self.previous_config_path is None:
            os.environ.pop("TRADINGOS_CONFIG_PATH", None)
        else:
            os.environ["TRADINGOS_CONFIG_PATH"] = self.previous_config_path
        clear_runtime_settings_cache()

    def test_default_configuration_has_a_versioned_source(self) -> None:
        settings = load_runtime_settings()

        self.assertEqual(settings.rule_version, "2026-07-15.20")
        self.assertEqual(settings.source, str(DEFAULT_CONFIG_PATH.resolve()))
        self.assertEqual(settings.get("runtime", "local_server", "host"), "0.0.0.0")
        self.assertEqual(settings.get("runtime", "local_server", "port"), 8000)
        self.assertEqual(settings.get("runtime", "snapshot_max_workers"), 4)
        self.assertEqual(settings.get("domain_knowledge", "technical", "history_bars"), 120)

    def test_technical_history_must_cover_every_configured_window(self) -> None:
        config = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
        config["domain_knowledge"]["technical"]["history_bars"] = 60

        with tempfile.TemporaryDirectory() as directory:
            override_path = Path(directory) / "invalid-technical-history.json"
            override_path.write_text(json.dumps(config), encoding="utf-8")
            os.environ["TRADINGOS_CONFIG_PATH"] = str(override_path)
            clear_runtime_settings_cache()

            with self.assertRaisesRegex(RuntimeError, "history_bars"):
                load_runtime_settings()

    def test_runtime_override_changes_scoring_and_model_defaults(self) -> None:
        config = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
        config["scoring"]["score_bounds"]["max"] = 90
        config["providers"]["models"][0]["default_model"] = "configured-model"

        with tempfile.TemporaryDirectory() as directory:
            override_path = Path(directory) / "tradingos.json"
            override_path.write_text(json.dumps(config), encoding="utf-8")
            os.environ["TRADINGOS_CONFIG_PATH"] = str(override_path)
            clear_runtime_settings_cache()

            self.assertEqual(clamp_score(100), 90)
            self.assertEqual(DeepSeekConfig(api_key=None).model, "configured-model")

    def test_invalid_configuration_fails_fast(self) -> None:
        config = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
        del config["providers"]["eastmoney"]["kline_url"]

        with tempfile.TemporaryDirectory() as directory:
            override_path = Path(directory) / "broken.json"
            override_path.write_text(json.dumps(config), encoding="utf-8")
            os.environ["TRADINGOS_CONFIG_PATH"] = str(override_path)
            clear_runtime_settings_cache()

            with self.assertRaises(RuntimeError):
                load_runtime_settings()

    def test_board_ladder_configuration_must_cover_every_consecutive_board(self) -> None:
        config = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
        config["providers"]["tushare"]["market_context"]["board_ladder_buckets"] = [
            {"label": "1 board", "minimum": 1, "maximum": 1},
            {"label": "3+ boards", "minimum": 3, "maximum": None},
        ]

        with tempfile.TemporaryDirectory() as directory:
            override_path = Path(directory) / "invalid-ladder.json"
            override_path.write_text(json.dumps(config), encoding="utf-8")
            os.environ["TRADINGOS_CONFIG_PATH"] = str(override_path)
            clear_runtime_settings_cache()

            with self.assertRaisesRegex(RuntimeError, "continuously cover"):
                load_runtime_settings()

    def test_missing_tushare_token_is_reported_as_unavailable_not_embedded(self) -> None:
        token_key = load_runtime_settings().get("providers", "tushare", "token_env")
        previous_token = os.environ.pop(token_key, None)
        try:
            provider = TushareMarketDataProvider(pro_client=None)
            signals = provider.get_market_signals("600519", "2026-07-10")
            self.assertEqual(signals.data_status, "unavailable")
            self.assertIn("unavailable", str(signals.unavailable_reasons).lower())
        finally:
            if previous_token is not None:
                os.environ[token_key] = previous_token


if __name__ == "__main__":
    unittest.main()
