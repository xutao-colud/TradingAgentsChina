from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable


ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class RegisteredTool:
    schema: dict[str, Any]
    handler: ToolHandler


class ToolRegistry:
    """Small dependency-free registry for independently mountable tool modules."""

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, schema: dict[str, Any], handler: ToolHandler) -> None:
        name = schema.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("Tool schema must have a non-empty name")
        if name in self._tools:
            raise ValueError(f"Tool already registered: {name}")
        self._tools[name] = RegisteredTool(schema=deepcopy(schema), handler=handler)

    def list_schemas(self) -> list[dict[str, Any]]:
        return [deepcopy(tool.schema) for tool in self._tools.values()]

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError(f"Unknown tool: {name}")
        required = tool.schema.get("inputSchema", {}).get("required", [])
        missing = [field for field in required if field not in arguments]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")
        return tool.handler(arguments)
