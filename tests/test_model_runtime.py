from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from app.graph.workflow import build_sample_workflow
from app.llm.runtime import ModelRuntime
from app.llm.prompt_contracts import EXPLANATION_COMPLETE_MARKER
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
                self.assertIn("反推验证", payload["messages"][0]["content"])
                self.assertIn("反推验证任务", payload["messages"][1]["content"])
                return {"choices": [{
                    "message": {"content": f"GLM 解释。\n{EXPLANATION_COMPLETE_MARKER}"},
                    "finish_reason": "stop",
                }]}

            runtime = ModelRuntime(f"{tmpdir}/model_settings.json", post_json=fake_post)
            runtime.configure("glm", "test-secret-key")
            report = build_sample_workflow().run("600519", "2026-07-10")
            explained = runtime.explain(report, {})
            self.assertEqual(explained.fundamental_score, report.fundamental_score)
            self.assertEqual(explained.model_interpretation, "GLM 解释。")
            self.assertEqual(explained.model_execution["provider_id"], "glm")
            self.assertEqual(explained.model_execution["model"], "glm-5.1")
            self.assertTrue(explained.model_execution["complete"])
            self.assertEqual(runtime.status()["last_execution"]["status"], "succeeded")

    def test_rejects_unsaved_ui_selection_before_calling_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            called = False

            def fake_post(url, headers, payload):
                nonlocal called
                called = True
                return {"choices": [{
                    "message": {"content": f"不应执行\n{EXPLANATION_COMPLETE_MARKER}"},
                    "finish_reason": "stop",
                }]}

            runtime = ModelRuntime(f"{tmpdir}/model_settings.json", post_json=fake_post)
            runtime.configure("glm", "test-secret-key", "glm-5.1")
            report = build_sample_workflow().run("600519", "2026-07-10")
            with self.assertRaisesRegex(RuntimeError, "模型选择尚未生效") as raised:
                runtime.explain(
                    report,
                    {},
                    expected_provider_id="qwen",
                    expected_model="qwen-plus",
                )
            self.assertIn("GLM（智谱）/glm-5.1", str(raised.exception))
            self.assertFalse(called)

    def test_provider_error_names_actual_provider_instead_of_deepseek(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            def fake_post(url, headers, payload):
                raise RuntimeError('Model API returned HTTP 401: {"message":"token invalid"}')

            runtime = ModelRuntime(f"{tmpdir}/model_settings.json", post_json=fake_post)
            runtime.configure("glm", "test-secret-key", "glm-5.1")
            report = build_sample_workflow().run("600519", "2026-07-10")
            with self.assertRaisesRegex(RuntimeError, "GLM（智谱） model glm-5.1") as raised:
                runtime.explain(report, {})
            self.assertNotIn("DeepSeek API", str(raised.exception))
            self.assertEqual(runtime.status()["last_execution"]["status"], "failed")

    def test_switching_provider_removes_previous_session_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            "os.environ",
            {"DEEPSEEK_API_KEY": "", "ZAI_API_KEY": "", "DASHSCOPE_API_KEY": ""},
        ):
            runtime = ModelRuntime(f"{tmpdir}/model_settings.json")
            runtime.configure("deepseek", "deepseek-secret-key")
            runtime.configure("glm", "glm-secret-key")
            providers = {item["id"]: item for item in runtime.status()["providers"]}
            self.assertEqual(providers["deepseek"]["key_source"], "missing")
            self.assertEqual(providers["glm"]["key_source"], "session")

    def test_portable_memory_export_excludes_model_runtime_settings_and_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = ModelRuntime(f"{tmpdir}/model_settings.json")
            runtime.configure("qwen", "session-secret-key")
            bundle = LocalMemoryStore(tmpdir).export_bundle()
            self.assertNotIn("session-secret-key", str(bundle))
            self.assertNotIn("model_settings", bundle)
