from __future__ import annotations

import tempfile
import unittest

from app.mcp.server import McpToolServer
from app.memory.local_store import LocalMemoryStore


class McpToolServerTest(unittest.TestCase):
    def test_initialize_and_list_tools(self) -> None:
        server = McpToolServer()
        initialize = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        assert initialize is not None
        self.assertEqual(initialize["result"]["protocolVersion"], "2025-06-18")

        listed = server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert listed is not None
        names = {tool["name"] for tool in listed["result"]["tools"]}
        self.assertIn("get_realtime_quote", names)
        self.assertIn("record_feedback", names)

    def test_quote_and_memory_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            server = McpToolServer(memory_store=LocalMemoryStore(tmpdir))
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
        response = McpToolServer().handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "get_money_flow", "arguments": {"symbol": "600519"}},
            }
        )
        assert response is not None
        self.assertEqual(response["error"]["code"], -32602)

    def test_custom_tool_can_be_registered_without_changing_server(self) -> None:
        server = McpToolServer()
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
