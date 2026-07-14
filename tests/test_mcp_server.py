from __future__ import annotations

import tempfile
import unittest

from app.mcp.server import McpToolServer
from app.data.providers.sample_provider import SampleMarketDataProvider
from app.memory.local_store import LocalMemoryStore


class McpToolServerTest(unittest.TestCase):
    def test_initialize_and_list_tools(self) -> None:
        server = McpToolServer(provider=SampleMarketDataProvider())
        initialize = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        assert initialize is not None
        self.assertEqual(initialize["result"]["protocolVersion"], "2025-06-18")

        listed = server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert listed is not None
        names = {tool["name"] for tool in listed["result"]["tools"]}
        self.assertIn("get_realtime_quote", names)
        self.assertIn("record_feedback", names)
        self.assertIn("scan_opportunity_pool", names)
        self.assertIn("get_opportunity_pool", names)

    def test_quote_and_memory_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            server = McpToolServer(provider=SampleMarketDataProvider(), memory_store=LocalMemoryStore(tmpdir))
            quote = server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "get_realtime_quote", "arguments": {"symbol": "600519"}},
                }
            )
            assert quote is not None
            content = quote["result"]["structuredContent"]
            self.assertEqual(content["symbol"], "600519.SH")
            self.assertIn("price", content)

            saved = server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "save_analysis_event",
                        "arguments": {
                            "symbol": "600519",
                            "analysis_date": "2026-07-10",
                            "report": {"conclusion": "中性观察"},
                        },
                    },
                }
            )
            assert saved is not None
            self.assertIn("event_id", saved["result"]["structuredContent"])

            feedback = server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "record_feedback",
                        "arguments": {
                            "symbol": "600519",
                            "feedback_type": "preference",
                            "user_comment": "我不喜欢追高",
                        },
                    },
                }
            )
            assert feedback is not None
            self.assertEqual(feedback["result"]["structuredContent"]["profile_version"], 2)

    def test_invalid_tool_arguments_return_json_rpc_error(self) -> None:
        response = McpToolServer(provider=SampleMarketDataProvider()).handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "get_money_flow", "arguments": {"symbol": "600519"}},
            }
        )
        assert response is not None
        self.assertEqual(response["error"]["code"], -32602)

    def test_opportunity_pool_tools_are_persisted_and_replayable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            server = McpToolServer(provider=SampleMarketDataProvider(), memory_store=LocalMemoryStore(tmpdir))
            scan = server.call_tool(
                "scan_opportunity_pool",
                {
                    "analysis_date": "2026-07-14",
                    "symbols": ["600519"],
                    "include_radar": False,
                    "maximum_level": 1,
                },
            )
            self.assertEqual(scan["level_counts"]["level1"], 1)
            self.assertEqual(scan["market_data_status"], "sample")
            latest = server.call_tool("get_opportunity_pool", {})
            self.assertEqual(latest["id"], scan["id"])
            replay = server.call_tool("replay_opportunity_pool", {"event_id": scan["memory_event_id"]})
            self.assertEqual(replay["pool_snapshot"]["id"], scan["id"])

    def test_custom_tool_can_be_registered_without_changing_server(self) -> None:
        server = McpToolServer(provider=SampleMarketDataProvider())
        server.registry.register(
            {
                "name": "get_strategy_note",
                "description": "A sample pluggable strategy note tool.",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            },
            lambda arguments: {"note": "插件已加载", "argument_count": len(arguments)},
        )
        response = server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "get_strategy_note", "arguments": {}},
            }
        )
        assert response is not None
        self.assertEqual(response["result"]["structuredContent"]["note"], "插件已加载")
