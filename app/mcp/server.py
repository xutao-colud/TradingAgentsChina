from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any

from app.data.providers.base import MarketDataProvider
from app.data.providers.production_provider import ProductionMarketDataProvider
from app.market.morning_radar import MorningMoneyRadarClient
from app.graph.workflow import AShareResearchWorkflow
from app.memory.local_store import LocalMemoryStore
from app.memory.models import FeedbackEvent
from app.opportunities.pipeline import OpportunityPipeline
from app.mcp.tool_schemas import find_tool_schema, list_tool_schemas
from app.rules.trading_rules import normalize_symbol
from app.tools.registry import ToolRegistry


class McpToolServer:
    """A small stdio-MCP compatible tool dispatcher.

    Production data is the default. Tests and offline demonstrations must inject
    an explicit sample provider so sample facts cannot leak into live tools.
    """

    protocol_version = "2025-06-18"

    def __init__(
        self,
        provider: MarketDataProvider | None = None,
        memory_store: LocalMemoryStore | None = None,
        registry: ToolRegistry | None = None,
    ) -> None:
        self.provider = provider or ProductionMarketDataProvider()
        self.memory_store = memory_store or LocalMemoryStore()
        self.registry = registry or build_builtin_registry(self.provider, self.memory_store)

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        request_id = request.get("id")
        method = request.get("method")
        if not isinstance(method, str):
            return self._error(request_id, -32600, "Invalid Request: method must be a string")

        if method == "notifications/initialized":
            return None
        if method == "initialize":
            return self._result(
                request_id,
                {
                    "protocolVersion": self.protocol_version,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "china-stock-market-mcp", "version": "0.1.0"},
                },
            )
        if method == "tools/list":
            return self._result(request_id, {"tools": self.registry.list_schemas()})
        if method == "tools/call":
            params = request.get("params", {})
            if not isinstance(params, dict):
                return self._error(request_id, -32602, "Invalid params")
            name = params.get("name")
            arguments = params.get("arguments", {})
            if not isinstance(name, str) or not isinstance(arguments, dict):
                return self._error(request_id, -32602, "tools/call requires name and object arguments")
            try:
                payload = self.call_tool(name, arguments)
            except (KeyError, TypeError, ValueError) as exc:
                return self._error(request_id, -32602, str(exc))
            return self._result(request_id, _tool_result(payload))
        return self._error(request_id, -32601, f"Method not found: {method}")

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.registry.call(name, arguments)

    @staticmethod
    def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def build_builtin_registry(provider: MarketDataProvider, memory_store: LocalMemoryStore) -> ToolRegistry:
    registry = ToolRegistry()

    def get_realtime_quote(arguments: dict[str, Any]) -> dict[str, Any]:
            symbol = normalize_symbol(str(arguments["symbol"]))
            bars = provider.get_daily_prices(symbol, date.today().isoformat(), lookback_days=2)
            if not bars:
                raise ValueError(f"No price data returned for {symbol}")
            latest = bars[-1]
            previous = bars[-2] if len(bars) > 1 else latest
            change_pct = 0.0 if previous.close == 0 else round((latest.close / previous.close - 1) * 100, 2)
            return {
                "symbol": symbol,
                "price": latest.close,
                "change_pct": change_pct,
                "volume": latest.volume,
                "amount": latest.amount,
                "as_of": latest.trade_date,
                "source": type(provider).__name__,
                "data_status": "latest_available",
            }

    def get_daily_bars(arguments: dict[str, Any]) -> dict[str, Any]:
            symbol = normalize_symbol(str(arguments["symbol"]))
            end_date = str(arguments["end_date"])
            bars = provider.get_daily_prices(symbol, end_date, lookback_days=30)
            return {"symbol": symbol, "bars": [asdict(bar) for bar in bars], "source": type(provider).__name__}

    def get_market_breadth(arguments: dict[str, Any]) -> dict[str, Any]:
            trade_date = str(arguments["trade_date"])
            context = provider.get_market_context(trade_date)
            payload = asdict(context)
            payload.update({"trade_date": trade_date, "source": type(provider).__name__})
            return payload

    def get_money_flow(arguments: dict[str, Any]) -> dict[str, Any]:
            symbol = normalize_symbol(str(arguments["symbol"]))
            trade_date = str(arguments["trade_date"])
            payload = asdict(provider.get_money_flow(symbol, trade_date))
            payload.update({"symbol": symbol, "trade_date": trade_date, "source": type(provider).__name__})
            return payload

    def get_morning_money_radar(arguments: dict[str, Any]) -> dict[str, Any]:
            limit = _optional_int(arguments.get("limit")) or 6
            return MorningMoneyRadarClient().fetch_snapshot(limit=limit).to_dict()

    def search_announcements(arguments: dict[str, Any]) -> dict[str, Any]:
            symbol = normalize_symbol(str(arguments["symbol"]))
            end_date = str(arguments["end_date"])
            keywords = [str(item) for item in arguments.get("keywords", [])]
            announcements = provider.get_announcements(symbol, end_date)
            if keywords:
                announcements = [
                    item
                    for item in announcements
                    if any(keyword.lower() in f"{item.title} {item.summary}".lower() for keyword in keywords)
                ]
            return {
                "symbol": symbol,
                "announcements": [asdict(item) for item in announcements],
                "source": type(provider).__name__,
            }

    def save_analysis_event(arguments: dict[str, Any]) -> dict[str, Any]:
            event = memory_store.save_external_analysis(
                symbol=normalize_symbol(str(arguments["symbol"])),
                analysis_date=str(arguments["analysis_date"]),
                report=dict(arguments["report"]),
                user_query=str(arguments["user_query"]) if arguments.get("user_query") else None,
            )
            return {"event_id": event.id, "created_at": event.created_at, "storage": "local_append_only"}

    def record_feedback(arguments: dict[str, Any]) -> dict[str, Any]:
            feedback = FeedbackEvent(
                symbol=normalize_symbol(str(arguments["symbol"])),
                feedback_type=str(arguments["feedback_type"]),
                user_comment=str(arguments["user_comment"]),
                analysis_report_id=_optional_str(arguments.get("analysis_report_id")),
                outcome_return_pct=_optional_float(arguments.get("outcome_return_pct")),
                outcome_days=_optional_int(arguments.get("outcome_days")),
                learned_rule=_optional_str(arguments.get("learned_rule")),
            )
            saved = memory_store.record_feedback(feedback)
            return {
                "feedback_event_id": saved.id,
                "profile_version": memory_store.load_profile().version,
                "storage": "local_append_only",
            }

    def scan_opportunity_pool(arguments: dict[str, Any]) -> dict[str, Any]:
            symbols = arguments.get("symbols", [])
            if not isinstance(symbols, list) or any(not isinstance(item, str) for item in symbols):
                raise ValueError("symbols must be an array of stock symbols")
            pipeline = OpportunityPipeline(
                AShareResearchWorkflow(provider),
                memory_store,
                morning_radar_client=MorningMoneyRadarClient(),
            )
            return pipeline.run(
                analysis_date=str(arguments["analysis_date"]),
                explicit_symbols=symbols,
                include_radar=arguments.get("include_radar") is not False,
                maximum_level=_optional_int(arguments.get("maximum_level")) or 3,
            )

    def get_opportunity_pool(arguments: dict[str, Any]) -> dict[str, Any]:
            return memory_store.load_opportunity_pool() or {
                "pipeline_status": "not_run",
                "candidates": [],
                "excluded": [],
            }

    def replay_opportunity_pool(arguments: dict[str, Any]) -> dict[str, Any]:
            return memory_store.replay_opportunity_run(str(arguments["event_id"]))

    handlers = {
        "get_realtime_quote": get_realtime_quote,
        "get_daily_bars": get_daily_bars,
        "get_market_breadth": get_market_breadth,
        "get_money_flow": get_money_flow,
        "get_morning_money_radar": get_morning_money_radar,
        "search_announcements": search_announcements,
        "save_analysis_event": save_analysis_event,
        "record_feedback": record_feedback,
        "scan_opportunity_pool": scan_opportunity_pool,
        "get_opportunity_pool": get_opportunity_pool,
        "replay_opportunity_pool": replay_opportunity_pool,
    }
    for schema in list_tool_schemas():
        registry.register(schema, handlers[schema["name"]])
    return registry


def _tool_result(payload: dict[str, Any]) -> dict[str, Any]:
    import json

    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "structuredContent": payload,
        "isError": False,
    }


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _optional_float(value: Any) -> float | None:
    return float(value) if value is not None else None


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None
