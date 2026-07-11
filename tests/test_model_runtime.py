from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.graph.workflow import build_default_workflow
from app.llm.runtime import ModelRuntime
from app.memory.local_store import LocalMemoryStore


class ModelRuntimeTest(unittest.TestCase):
    def test_configures_session_key_without_exposing_or_persisting_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = ModelRuntime(f"{tmpdir}/model_settings.json")
            status = runtime.configure("glm", "test-secret-key", "glm-5.1")
            self.assertEqual(status["active_provider"], "glm")
            self.assertNotIn("test-secret-key", str(status))
            stored = Path(tmpdir, "model_settings.json").read_text(encoding="utf-8")
            self.assertNotIn("test-secret-key", stored)

    def test_selected_provider_explains_without_changing_report_scores(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            def fake_post(url, headers, payload):
                self.assertEqual(url, "https://open.bigmodel.cn/api/paas/v4/chat/completions")
                self.assertEqual(payload["model"], "glm-5.1")
                return {"choices": [{"message": {"content": "GLM 解释。"}}]}

            runtime = ModelRuntime(f"{tmpdir}/model_settings.json", post_json=fake_post)
            runtime.configure("glm", "test-secret-key")
            report = build_default_workflow().run("600519", "2026-07-10")
            explained = runtime.explain(report, {})
            self.assertEqual(explained.fundamental_score, report.fundamental_score)
            self.assertEqual(explained.model_interpretation, "GLM 解释。")

    def test_portable_memory_export_excludes_model_runtime_settings_and_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = ModelRuntime(f"{tmpdir}/model_settings.json")
            runtime.configure("qwen", "session-secret-key")
            bundle = LocalMemoryStore(tmpdir).export_bundle()
            self.assertNotIn("session-secret-key", str(bundle))
            self.assertNotIn("model_settings", bundle)
