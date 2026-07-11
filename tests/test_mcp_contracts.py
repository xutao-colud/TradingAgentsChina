import json
import unittest
from pathlib import Path

from app.llm.config import DeepSeekConfig
from app.mcp.tool_schemas import find_tool_schema, list_tool_schemas


class McpContractsTest(unittest.TestCase):
    def test_core_tool_schemas_are_available(self) -> None:
        names = {tool["name"] for tool in list_tool_schemas()}
        self.assertIn("get_realtime_quote", names)
        self.assertIn("get_market_breadth", names)
        self.assertIn("save_analysis_event", names)
        self.assertIn("record_feedback", names)

    def test_tool_schema_has_json_schema_required_fields(self) -> None:
        tool = find_tool_schema("get_realtime_quote")
        self.assertIsNotNone(tool)
        assert tool is not None
        self.assertEqual(tool["inputSchema"]["type"], "object")
        self.assertIn("symbol", tool["inputSchema"]["required"])

    def test_json_manifest_matches_python_tool_names(self) -> None:
        manifest = json.loads(Path("mcp/china_stock_tools.json").read_text(encoding="utf-8"))
        json_names = {tool["name"] for tool in manifest["tools"]}
        python_names = {tool["name"] for tool in list_tool_schemas()}
        self.assertEqual(json_names, python_names)

    def test_deepseek_config_defaults_to_current_model(self) -> None:
        config = DeepSeekConfig(api_key=None)
        self.assertEqual(config.base_url, "https://api.deepseek.com")
        self.assertEqual(config.model, "deepseek-v4-pro")
        self.assertFalse(config.is_configured())


if __name__ == "__main__":
    unittest.main()

