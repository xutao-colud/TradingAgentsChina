from __future__ import annotations

import argparse
import json
from dataclasses import replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from app.config.runtime import load_runtime_settings
from app.graph.workflow import AShareResearchWorkflow, build_default_workflow, build_production_workflow
from app.llm.runtime import ModelRuntime
from app.mcp.server import McpToolServer
from app.memory.local_store import LocalMemoryStore
from app.memory.models import FeedbackEvent
from app.market.morning_radar import MorningMoneyRadarClient
from app.market.realtime import SinaRealtimeQuoteClient
from app.market.stock_snapshot import EastmoneyStockSnapshotClient
from app.playbooks.catalog import get_playbook, list_playbooks
from app.portfolio.snapshot import build_portfolio_snapshot, quote_advice


STATIC_DIR = Path(__file__).with_name("static")


class ResearchWebApp:
    """Application service shared by HTTP handlers and fast tests."""

    def __init__(
        self,
        memory_store: LocalMemoryStore,
        workflow: AShareResearchWorkflow | None = None,
        quote_client: SinaRealtimeQuoteClient | None = None,
        morning_radar_client: MorningMoneyRadarClient | None = None,
        stock_snapshot_client: EastmoneyStockSnapshotClient | None = None,
        model_runtime: ModelRuntime | None = None,
    ) -> None:
        self.memory_store = memory_store
        self.workflow = workflow or build_default_workflow()
        self.mcp_server = McpToolServer(provider=self.workflow.provider, memory_store=memory_store)
        self.quote_client = quote_client or SinaRealtimeQuoteClient()
        self.morning_radar_client = morning_radar_client or MorningMoneyRadarClient()
        self.stock_snapshot_client = stock_snapshot_client if stock_snapshot_client is not None else (None if quote_client is not None else EastmoneyStockSnapshotClient())
        self.model_runtime = model_runtime or ModelRuntime(memory_store.root / "model_settings.json")

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "mode": "local", "data_provider": type(self.workflow.provider).__name__}

    def profile(self) -> dict[str, Any]:
        return self.memory_store.load_profile().to_dict()

    def tools(self) -> list[dict[str, Any]]:
        return self.mcp_server.registry.list_schemas()

    def playbooks(self) -> dict[str, Any]:
        return {
            "active_playbook": self.memory_store.load_profile().active_playbook,
            "playbooks": [item.to_dict() for item in list_playbooks()],
        }

    def model_status(self) -> dict[str, Any]:
        return self.model_runtime.status()

    def configure_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider_id = payload.get("provider_id")
        api_key = payload.get("api_key")
        if not isinstance(provider_id, str) or not isinstance(api_key, str):
            raise ValueError("provider_id and api_key are required")
        return self.model_runtime.configure(provider_id, api_key, _optional_string(payload.get("model")))

    def clear_model_key(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider_id = payload.get("provider_id")
        if not isinstance(provider_id, str):
            raise ValueError("provider_id is required")
        return self.model_runtime.clear_session_key(provider_id)

    def activate_playbook(self, payload: dict[str, Any]) -> dict[str, Any]:
        playbook_id = payload.get("playbook_id")
        if not isinstance(playbook_id, str):
            raise ValueError("playbook_id is required")
        playbook = get_playbook(playbook_id)
        profile = self.memory_store.set_active_playbook(playbook.id)
        return {"active_playbook": playbook.to_dict(), "trading_profile": profile.to_dict()}

    def watchlist(self) -> dict[str, Any]:
        return {"items": self.memory_store.load_watchlist()}

    def add_watchlist(self, payload: dict[str, Any]) -> dict[str, Any]:
        symbol = payload.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol is required")
        return {"items": self.memory_store.add_watchlist(symbol, _optional_string(payload.get("note")))}

    def remove_watchlist(self, payload: dict[str, Any]) -> dict[str, Any]:
        symbol = payload.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol is required")
        return {"items": self.memory_store.remove_watchlist(symbol)}

    def update_cash_balance(self, payload: dict[str, Any]) -> dict[str, Any]:
        value = payload.get("cash_balance")
        if value is None:
            raise ValueError("cash_balance is required")
        return self.memory_store.set_cash_balance(float(value))

    def upsert_position(self, payload: dict[str, Any]) -> dict[str, Any]:
        symbol = payload.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol is required")
        return self.memory_store.upsert_position(symbol, float(payload.get("quantity", 0)), float(payload.get("cost_price", -1)))

    def remove_position(self, payload: dict[str, Any]) -> dict[str, Any]:
        symbol = payload.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol is required")
        return self.memory_store.remove_position(symbol)

    def portfolio(self) -> dict[str, Any]:
        return build_portfolio_snapshot(self.memory_store.load_portfolio(), {})

    def refresh_market(self) -> dict[str, Any]:
        watchlist = self.memory_store.load_watchlist()
        portfolio = self.memory_store.load_portfolio()
        symbols = [item["symbol"] for item in watchlist] + [item["symbol"] for item in portfolio["positions"]]
        unique_symbols = list(dict.fromkeys(symbols))
        snapshots = self.stock_snapshot_client.fetch_snapshots(unique_symbols) if self.stock_snapshot_client else {}
        quotes = {
            symbol: snapshot.to_quote()
            for symbol, snapshot in snapshots.items()
            if snapshot.data_status != "unavailable" and snapshot.price is not None
        }
        missing_quote_symbols = [symbol for symbol in unique_symbols if symbol not in quotes]
        if missing_quote_symbols:
            quotes.update(self.quote_client.fetch_quotes(missing_quote_symbols))
        watch_rows = [
            {
                **item,
                "quote": quotes[item["symbol"]].to_dict(),
                "snapshot": snapshots[item["symbol"]].to_dict() if item["symbol"] in snapshots else None,
                "advice": quote_advice(quotes[item["symbol"]]),
            }
            for item in watchlist
            if item["symbol"] in quotes
        ]
        source = "eastmoney_push2"
        if missing_quote_symbols and snapshots:
            source = "eastmoney_push2+sina_fallback"
        elif not snapshots:
            source = "sina"
        return {
            "watchlist": watch_rows,
            "portfolio": build_portfolio_snapshot(portfolio, quotes),
            "source": source,
        }

    def morning_radar(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        limit = _optional_int(payload.get("limit")) or 6
        return self.morning_radar_client.fetch_snapshot(limit=limit).to_dict()

    def analyze(self, payload: dict[str, Any]) -> dict[str, Any]:
        symbol = payload.get("symbol")
        analysis_date = payload.get("analysis_date")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol is required")
        if not isinstance(analysis_date, str) or not analysis_date:
            raise ValueError("analysis_date is required")

        question = str(payload.get("question") or f"分析 {symbol}（{analysis_date}）")
        context = self.memory_store.build_context(symbol)
        report = self.workflow.run(
            symbol,
            analysis_date,
            trading_profile=self.memory_store.load_profile(),
            user_question=question,
        )
        model_name = "deterministic-mvp"
        if payload.get("include_realtime") is True:
            try:
                if self.stock_snapshot_client:
                    snapshot = self.stock_snapshot_client.fetch_snapshot(report.symbol)
                    quote = snapshot.to_quote() if snapshot.data_status != "unavailable" and snapshot.price is not None else None
                    if quote is None:
                        quote = self.quote_client.fetch_quotes([report.symbol]).get(report.symbol)
                else:
                    quote = self.quote_client.fetch_quotes([symbol]).get(report.symbol)
                if quote:
                    report = replace(report, realtime_quote=quote.to_dict())
                    context["realtime_quote"] = quote.to_dict()
            except ValueError as exc:
                report = replace(report, realtime_quote={"symbol": report.symbol, "data_status": "unavailable", "error": str(exc)})
                context["realtime_quote"] = report.realtime_quote
        if payload.get("model_explain") is True or payload.get("deepseek_explain") is True:
            report = self.model_runtime.explain(report, context)
            status = self.model_runtime.status()
            model_name = f"{status['active_provider']}:{status['active_model']}"

        event = self.memory_store.save_analysis(report, user_query=question, model_name=model_name)
        interaction = self.memory_store.save_interaction_summary(report, question, event.id)
        result = report.to_dict()
        result["memory_event_id"] = event.id
        result["interaction_event_id"] = interaction.id
        return result

    def feedback(self, payload: dict[str, Any]) -> dict[str, Any]:
        symbol = payload.get("symbol")
        comment = payload.get("user_comment")
        feedback_type = payload.get("feedback_type", "preference")
        allowed = {"preference", "outcome", "correction", "rule"}
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol is required")
        if not isinstance(comment, str) or not comment.strip():
            raise ValueError("user_comment is required")
        if feedback_type not in allowed:
            raise ValueError("feedback_type is invalid")
        feedback = self.memory_store.record_feedback(
            FeedbackEvent(
                symbol=symbol,
                feedback_type=feedback_type,
                user_comment=comment,
                learned_rule=_optional_string(payload.get("learned_rule")),
                analysis_report_id=_optional_string(payload.get("analysis_report_id")),
                outcome_return_pct=_optional_float(payload.get("outcome_return_pct")),
                outcome_days=_optional_int(payload.get("outcome_days")),
            )
        )
        return {"feedback_event": feedback.to_dict(), "trading_profile": self.profile()}

    def import_memory(self, payload: dict[str, Any]) -> dict[str, int]:
        return self.memory_store.import_bundle(payload)

    def export_memory(self) -> dict[str, Any]:
        return self.memory_store.export_bundle()


class TradingDeskHandler(BaseHTTPRequestHandler):
    app: ResearchWebApp
    allow_secret_configuration = True

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/health":
            self._write_json(HTTPStatus.OK, self.app.health())
            return
        if self.path == "/api/profile":
            self._write_json(HTTPStatus.OK, self.app.profile())
            return
        if self.path == "/api/tools":
            self._write_json(HTTPStatus.OK, {"tools": self.app.tools()})
            return
        if self.path == "/api/playbooks":
            self._write_json(HTTPStatus.OK, self.app.playbooks())
            return
        if self.path == "/api/watchlist":
            self._write_json(HTTPStatus.OK, self.app.watchlist())
            return
        if self.path == "/api/portfolio":
            self._write_json(HTTPStatus.OK, self.app.portfolio())
            return
        if self.path == "/api/models":
            self._write_json(HTTPStatus.OK, self.app.model_status())
            return
        self._serve_static()

    def do_POST(self) -> None:  # noqa: N802
        try:
            payload = self._read_json()
            if self.path == "/api/analyze":
                self._write_json(HTTPStatus.OK, self.app.analyze(payload))
            elif self.path == "/api/feedback":
                self._write_json(HTTPStatus.OK, self.app.feedback(payload))
            elif self.path == "/api/playbook/activate":
                self._write_json(HTTPStatus.OK, self.app.activate_playbook(payload))
            elif self.path == "/api/watchlist":
                self._write_json(HTTPStatus.OK, self.app.add_watchlist(payload))
            elif self.path == "/api/watchlist/remove":
                self._write_json(HTTPStatus.OK, self.app.remove_watchlist(payload))
            elif self.path == "/api/portfolio/cash":
                self._write_json(HTTPStatus.OK, self.app.update_cash_balance(payload))
            elif self.path == "/api/portfolio/position":
                self._write_json(HTTPStatus.OK, self.app.upsert_position(payload))
            elif self.path == "/api/portfolio/position/remove":
                self._write_json(HTTPStatus.OK, self.app.remove_position(payload))
            elif self.path == "/api/market/refresh":
                self._write_json(HTTPStatus.OK, self.app.refresh_market())
            elif self.path == "/api/morning/radar":
                self._write_json(HTTPStatus.OK, self.app.morning_radar(payload))
            elif self.path == "/api/models/configure":
                if not self.allow_secret_configuration:
                    self._write_json(HTTPStatus.FORBIDDEN, {"error": "Model key configuration is disabled on non-local hosts"})
                else:
                    self._write_json(HTTPStatus.OK, self.app.configure_model(payload))
            elif self.path == "/api/models/clear":
                if not self.allow_secret_configuration:
                    self._write_json(HTTPStatus.FORBIDDEN, {"error": "Model key configuration is disabled on non-local hosts"})
                else:
                    self._write_json(HTTPStatus.OK, self.app.clear_model_key(payload))
            elif self.path == "/api/memory/import":
                self._write_json(HTTPStatus.OK, {"added_events": self.app.import_memory(payload)})
            elif self.path == "/api/memory/export":
                self._write_json(
                    HTTPStatus.OK,
                    self.app.export_memory(),
                    headers={"Content-Disposition": 'attachment; filename="trading-agents-memory.json"'},
                )
            else:
                self._write_json(HTTPStatus.NOT_FOUND, {"error": "Unknown API route"})
        except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 2_000_000:
            raise ValueError("Request body must be JSON and smaller than 2 MB")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _serve_static(self) -> None:
        path_map = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/index.html": ("index.html", "text/html; charset=utf-8"),
            "/styles.css": ("styles.css", "text/css; charset=utf-8"),
            "/app.js": ("app.js", "application/javascript; charset=utf-8"),
        }
        target = path_map.get(self.path)
        if target is None:
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return
        filename, content_type = target
        body = (STATIC_DIR / filename).read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._send_security_headers(cache_control="public, max-age=60")
        self.end_headers()
        self.wfile.write(body)

    def _write_json(self, status: HTTPStatus, payload: dict[str, Any], headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_security_headers(cache_control="no-store")
        if headers:
            for name, value in headers.items():
                self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_security_headers(self, cache_control: str) -> None:
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
        )

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[web] {format % args}")


def create_server(host: str | None = None, port: int | None = None, memory_dir: str = "data/memory", provider_name: str = "production") -> ThreadingHTTPServer:
    server_config = load_runtime_settings().get("runtime", "local_server")
    host = host or server_config["host"]
    port = port if port is not None else server_config["port"]
    snapshot_client = EastmoneyStockSnapshotClient()
    TradingDeskHandler.app = ResearchWebApp(
        LocalMemoryStore(memory_dir),
        workflow=build_production_workflow() if provider_name == "production" else build_default_workflow(),
        stock_snapshot_client=snapshot_client,
    )
    TradingDeskHandler.allow_secret_configuration = host in {"127.0.0.1", "localhost", "::1"}
    return ThreadingHTTPServer((host, port), TradingDeskHandler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local A-share research dashboard.")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--memory-dir", default="data/memory")
    parser.add_argument("--provider", choices=["production", "sample"], default="production")
    args = parser.parse_args()
    server = create_server(args.host, args.port, args.memory_dir, args.provider)
    actual_host, actual_port = server.server_address[:2]
    print(f"TradingAgentsChina is running at http://{actual_host}:{actual_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None


def _optional_float(value: Any) -> float | None:
    return float(value) if value is not None else None


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None


if __name__ == "__main__":
    main()
