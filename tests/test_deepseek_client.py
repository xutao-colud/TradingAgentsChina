from __future__ import annotations

import unittest
from unittest.mock import patch
from urllib.error import URLError

from app.graph.workflow import build_sample_workflow
from app.llm.config import DeepSeekConfig
from app.llm.deepseek_client import DeepSeekClient, _post_json


class DeepSeekClientTest(unittest.TestCase):
    def test_explain_uses_deterministic_report_without_overwriting_scores(self) -> None:
        captured: dict[str, object] = {}

        def fake_post(url: str, headers: dict[str, str], payload: dict[str, object]) -> dict[str, object]:
            captured["url"] = url
            captured["headers"] = headers
            captured["payload"] = payload
            return {"choices": [{"message": {"content": "证据链清晰，但仍需核验公告原文。"}}]}

        report = build_sample_workflow().run("600519", "2026-07-10")
        explained = DeepSeekClient(DeepSeekConfig(api_key="test-key"), post_json=fake_post).explain(
            report,
            {"trading_profile": {"style": "趋势+价值混合"}},
        )

        self.assertEqual(explained.fundamental_score, report.fundamental_score)
        self.assertEqual(explained.conclusion, report.conclusion)
        self.assertEqual(explained.model_interpretation, "证据链清晰，但仍需核验公告原文。")
        self.assertEqual(captured["url"], "https://api.deepseek.com/chat/completions")
        headers = captured["headers"]
        assert isinstance(headers, dict)
        self.assertEqual(headers["Authorization"], "Bearer test-key")
        payload = captured["payload"]
        assert isinstance(payload, dict)
        messages = payload["messages"]
        assert isinstance(messages, list)
        self.assertIn("反推验证", messages[0]["content"])
        self.assertIn("不要输出隐藏思维链", messages[0]["content"])
        self.assertIn("data_status", messages[0]["content"])
        self.assertIn("反推验证任务", messages[1]["content"])
        self.assertIn('"data_status": "样例数据"', messages[1]["content"])
        self.assertIn("如果当前结论偏乐观", messages[1]["content"])

    def test_explain_requires_api_key(self) -> None:
        report = build_sample_workflow().run("600519", "2026-07-10")
        with self.assertRaisesRegex(RuntimeError, "DEEPSEEK_API_KEY"):
            DeepSeekClient(DeepSeekConfig(api_key=None)).explain(report, {})

    def test_reports_socket_policy_denial_without_claiming_an_api_failure(self) -> None:
        denied = URLError(OSError("[WinError 10013] An attempt was made to access a socket in a way forbidden by its access permissions"))
        with patch("app.llm.deepseek_client.urlopen", side_effect=denied):
            with self.assertRaisesRegex(RuntimeError, "Outbound network access was denied"):
                _post_json("https://api.deepseek.com/chat/completions", {}, {})
