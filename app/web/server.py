from __future__ import annotations

import argparse
import errno
import json
import socket
from dataclasses import replace
from datetime import datetime
from functools import lru_cache
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from pathlib import Path
from threading import RLock
from typing import Any, Callable
from urllib.parse import urlsplit

from app.config.runtime import load_runtime_settings
from app.data.verified_cache import NullVerifiedDatasetCache, VerifiedDatasetCache
from app.graph.workflow import AShareResearchWorkflow, build_default_workflow, build_production_workflow, build_sample_workflow
from app.llm.runtime import ModelRuntime
from app.mcp.server import McpToolServer
from app.memory.local_store import LocalMemoryStore
from app.memory.models import FeedbackEvent
from app.opportunities.pipeline import OpportunityPipeline
from app.market.morning_radar import MorningMoneyRadarClient
from app.market.realtime import (
    RealtimeQuote,
    SinaRealtimeQuoteClient,
    TencentRealtimeQuoteClient,
    quote_is_usable,
    quote_priority,
)
from app.market.stock_snapshot import EastmoneyStockSnapshotClient
from app.market.tushare_radar import TushareIndustryRadarFallback
from app.playbooks.catalog import get_playbook, list_playbooks
from app.portfolio.snapshot import build_portfolio_snapshot, quote_advice
from app.reporting.presentation import public_report_payload
from app.rules.trading_rules import normalize_symbol
from app.web.team_access import (
    ResearchCapacityGate,
    TestAccessCapacityError,
    TestAccessSession,
    TestAccessSessionRegistry,
    UserResearchAppPool,
)


STATIC_DIR = Path(__file__).with_name("static")
MODEL_CONFIG_LOCAL_ONLY_ERROR = (
    "模型密钥只能在运行服务的这台电脑上配置。"
    "请在服务器电脑打开 http://127.0.0.1:8000，或使用该电脑自己的局域网 IP；"
    "其他局域网设备请通过环境变量配置密钥。"
)


class ExclusiveThreadingHTTPServer(ThreadingHTTPServer):
    """Prevent two dashboard versions from sharing one Windows port."""

    allow_reuse_address = False

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


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
        quote_fallback_clients: list[Any] | None = None,
        quote_cache: VerifiedDatasetCache | NullVerifiedDatasetCache | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.memory_store = memory_store
        self.workflow = workflow or build_default_workflow()
        self.mcp_server = McpToolServer(provider=self.workflow.provider, memory_store=memory_store)
        self.quote_client = quote_client or SinaRealtimeQuoteClient()
        self.stock_snapshot_client = stock_snapshot_client if stock_snapshot_client is not None else (None if quote_client is not None else EastmoneyStockSnapshotClient())
        if quote_fallback_clients is not None:
            self.quote_fallback_clients = quote_fallback_clients
        elif quote_client is not None:
            self.quote_fallback_clients = [quote_client]
        else:
            clients = {"tencent": TencentRealtimeQuoteClient(), "sina": self.quote_client}
            order = load_runtime_settings().get("runtime", "realtime_ticker", "fallback_providers")
            self.quote_fallback_clients = [clients[provider] for provider in order]
        self.quote_cache = quote_cache or NullVerifiedDatasetCache()
        self._quote_cache_lock = RLock()
        self._now = now or datetime.now
        sector_fallback = _build_sector_radar_fallback(self.workflow.provider)
        self.morning_radar_client = morning_radar_client or MorningMoneyRadarClient(
            quote_fetcher=self._fetch_current_quotes,
            secondary_fetcher=sector_fallback.fetch_snapshot if sector_fallback else None,
        )
        self.model_runtime = model_runtime or ModelRuntime(memory_store.root / "model_settings.json")
        self.opportunity_pipeline = OpportunityPipeline(
            self.workflow,
            memory_store,
            stock_snapshot_client=self.stock_snapshot_client,
            morning_radar_client=self.morning_radar_client,
        )

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "mode": "local",
            "data_provider": type(self.workflow.provider).__name__,
            "realtime_ticker": load_runtime_settings().get("runtime", "realtime_ticker"),
        }

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
        snapshot_error: str | None = None
        try:
            snapshots = self.stock_snapshot_client.fetch_snapshots(unique_symbols) if self.stock_snapshot_client else {}
        except Exception as exc:
            snapshots = {}
            snapshot_error = f"{type(exc).__name__}: {exc}"
        quotes = self._complete_quotes(
            unique_symbols,
            {symbol: snapshot.to_quote() for symbol, snapshot in snapshots.items()},
        )
        watch_rows = [
            {
                **item,
                "quote": quotes[item["symbol"]].to_dict(),
                "snapshot": snapshots[item["symbol"]].to_dict() if item["symbol"] in snapshots else None,
                "advice": quote_advice(quotes[item["symbol"]]),
            }
            for item in watchlist
        ]
        available_sources = list(dict.fromkeys(
            quote.source for quote in quotes.values() if quote_is_usable(quote, self._now())
        ))
        cache_replay_count = sum(
            quote.source.startswith("verified_quote_cache:")
            for quote in quotes.values()
        )
        return {
            "watchlist": watch_rows,
            "portfolio": build_portfolio_snapshot(portfolio, quotes),
            "source": "+".join(available_sources) if available_sources else "unavailable",
            "cache_replay_count": cache_replay_count,
            "warnings": [f"个股快照源本轮失败：{snapshot_error}"] if snapshot_error else [],
        }

    def refresh_ticker(self) -> dict[str, Any]:
        """Refresh only prices for tracked symbols; full snapshots remain user-triggered."""
        watchlist = self.memory_store.load_watchlist()
        portfolio = self.memory_store.load_portfolio()
        symbols = [item["symbol"] for item in watchlist] + [item["symbol"] for item in portfolio["positions"]]
        maximum = int(load_runtime_settings().get("runtime", "realtime_ticker", "maximum_symbols"))
        unique_symbols = list(dict.fromkeys(symbols))[:maximum]
        primary_quotes: dict[str, RealtimeQuote] = {}
        fetch_quotes = getattr(self.stock_snapshot_client, "fetch_quotes", None)
        if callable(fetch_quotes):
            try:
                primary_quotes.update(fetch_quotes(unique_symbols))
            except Exception:
                primary_quotes = {}
        quotes = self._complete_quotes(unique_symbols, primary_quotes)
        available_sources = list(dict.fromkeys(
            quote.source
            for quote in quotes.values()
            if quote_is_usable(quote, self._now())
        ))
        ticker_config = load_runtime_settings().get("runtime", "realtime_ticker")
        live_session = any(
            quote.data_status == "real_time" and quote_is_usable(quote, self._now())
            for quote in quotes.values()
        )
        return {
            "quotes": {symbol: quote.to_dict() for symbol, quote in quotes.items()},
            "portfolio": build_portfolio_snapshot(portfolio, quotes),
            "source": "+".join(available_sources) if available_sources else "unavailable",
            "tracked_count": len(unique_symbols),
            "refresh_interval_ms": ticker_config["refresh_interval_ms"] if live_session else ticker_config["non_realtime_interval_ms"],
            "live_session": live_session,
            "cache_replay_count": sum(
                quote.source.startswith("verified_quote_cache:")
                for quote in quotes.values()
            ),
        }

    def _complete_quotes(
        self,
        symbols: list[str],
        primary_quotes: dict[str, RealtimeQuote],
    ) -> dict[str, RealtimeQuote]:
        """Complete tracked quotes without ever dropping a persisted symbol."""
        current = self._now()
        quotes: dict[str, RealtimeQuote] = {}

        def merge(candidates: dict[str, RealtimeQuote]) -> None:
            for symbol, quote in candidates.items():
                if symbol not in symbols or not quote_is_usable(quote, current):
                    continue
                existing = quotes.get(symbol)
                if existing is None or quote_priority(quote, current) > quote_priority(existing, current):
                    quotes[symbol] = quote

        merge(primary_quotes)
        for client in self.quote_fallback_clients:
            unresolved = [
                symbol
                for symbol in symbols
                if quote_priority(quotes.get(symbol, _unavailable_realtime_quote(symbol)), current)[0] < 3
            ]
            if not unresolved:
                break
            try:
                secondary = client.fetch_quotes(unresolved)
            except (OSError, RuntimeError, ValueError):
                secondary = {}
            merge(secondary)
        for symbol in symbols:
            cached = self._load_verified_quote(symbol)
            if cached is not None:
                merge({symbol: cached})
        self._remember_verified_quotes(quotes)
        daily_close_quotes: dict[str, RealtimeQuote] = {}
        for symbol in symbols:
            if symbol not in quotes:
                daily_close = self._load_latest_daily_close_quote(symbol)
                if daily_close is not None:
                    daily_close_quotes[symbol] = daily_close
                    merge({symbol: daily_close})
        self._remember_verified_quotes(daily_close_quotes)
        for symbol in symbols:
            quotes.setdefault(symbol, _unavailable_realtime_quote(symbol))
        return quotes

    def _remember_verified_quotes(self, quotes: dict[str, RealtimeQuote]) -> None:
        current = self._now()
        with self._quote_cache_lock:
            for symbol, quote in quotes.items():
                if not quote_is_usable(quote, current) or quote.source.startswith("verified_quote_cache:"):
                    continue
                as_of = "T".join(filter(None, [quote.trade_date, quote.trade_time]))
                try:
                    self.quote_cache.save(
                        "realtime_quote",
                        symbol,
                        quote,
                        source_type=quote.source,
                        as_of=as_of or current.date().isoformat(),
                    )
                except (OSError, TypeError, ValueError):
                    continue

    def _load_verified_quote(self, symbol: str) -> RealtimeQuote | None:
        with self._quote_cache_lock:
            loaded = self.quote_cache.load(
                "realtime_quote",
                symbol,
                lambda row: RealtimeQuote(**row),
            )
            if loaded is None:
                return None
            quote, metadata = loaded
            if not quote_is_usable(quote, self._now()):
                return None
            return replace(
                quote,
                source=f"verified_quote_cache:{metadata['source_type']}",
                data_status="latest_available",
                error=(
                    "实时行情源本轮未返回更优数据，回放完整性校验通过的"
                    f"最近交易日快照（数据时间：{metadata['as_of']}）。"
                ),
            )

    def _load_latest_daily_close_quote(self, symbol: str) -> RealtimeQuote | None:
        """Use real daily bars as the last resort; sample data never enters this path."""
        provider = self.workflow.provider
        if getattr(provider, "data_mode", "production") != "production":
            return None
        current = self._now()
        bars = int(load_runtime_settings().get("runtime", "realtime_ticker", "daily_close_fallback_bars"))
        analysis_date = current.date().isoformat()
        try:
            prices = provider.get_daily_prices(symbol, analysis_date, lookback_days=bars)
        except Exception:
            return None
        ordered = sorted(
            (
                item
                for item in prices
                if item.close > 0 and item.volume >= 0 and item.trade_date <= analysis_date
            ),
            key=lambda item: item.trade_date,
        )
        if not ordered:
            return None
        latest = ordered[-1]
        previous_close = ordered[-2].close if len(ordered) > 1 and ordered[-2].close > 0 else None
        change_pct = (
            round((latest.close / previous_close - 1) * 100, 4)
            if previous_close is not None
            else None
        )
        source_type = "production_daily_prices"
        try:
            evidence = provider.get_evidence_sources(symbol, analysis_date)
            price_source = next((item for item in evidence if item.id == "price-001"), None)
            if price_source is not None:
                source_type = price_source.source_type
        except Exception:
            pass
        quote = RealtimeQuote(
            symbol=symbol,
            name=None,
            price=latest.close,
            previous_close=previous_close,
            change_pct=change_pct,
            volume=latest.volume,
            amount=latest.amount,
            trade_date=latest.trade_date,
            trade_time="15:00:00",
            source=f"daily_close:{source_type}",
            data_status="latest_available",
            error="实时报价不可用，已切换到真实日线 Provider 的最近交易日收盘快照。",
        )
        return quote if quote_is_usable(quote, current) else None

    def _fetch_current_quotes(self, symbols: list[str]) -> dict[str, RealtimeQuote]:
        """Use the same verified failover chain for ticker and radar fallbacks."""
        normalized = list(dict.fromkeys(normalize_symbol(symbol) for symbol in symbols))
        primary_quotes: dict[str, RealtimeQuote] = {}
        fetch_quotes = getattr(self.stock_snapshot_client, "fetch_quotes", None)
        if callable(fetch_quotes):
            try:
                primary_quotes.update(fetch_quotes(normalized))
            except (OSError, RuntimeError, ValueError):
                primary_quotes = {}
        return self._complete_quotes(normalized, primary_quotes)

    def morning_radar(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        settings = load_runtime_settings().get("morning_radar")
        limit = _optional_int(payload.get("limit")) or settings["default_limit"]
        radar = self.morning_radar_client.fetch_snapshot(
            limit=limit,
            fallback_symbols=self._radar_tracked_symbols(),
        )
        if radar.data_status == "tracked_universe" and self.stock_snapshot_client:
            radar = self._enrich_tracked_radar_money_flow(radar)
        return radar.to_dict()

    def _enrich_tracked_radar_money_flow(self, radar: Any) -> Any:
        """Attach verified per-stock flow only; never substitute it for sector flow."""
        symbols = [item.symbol for item in radar.fast_movers]
        snapshots = self.stock_snapshot_client.fetch_snapshots(symbols)
        enriched = []
        has_verified_flow = False
        for item in radar.fast_movers:
            snapshot = snapshots.get(item.symbol)
            if snapshot is None or snapshot.data_status == "unavailable":
                enriched.append(item)
                continue
            flow = snapshot.money_flow
            has_verified_flow = has_verified_flow or (flow is not None and flow.main_net_inflow is not None)
            enriched.append(
                replace(
                    item,
                    name=snapshot.name or item.name,
                    price=snapshot.price if snapshot.price is not None else item.price,
                    change_pct=snapshot.change_pct if snapshot.change_pct is not None else item.change_pct,
                    amount=snapshot.amount if snapshot.amount is not None else item.amount,
                    main_net_inflow=flow.main_net_inflow if flow else None,
                    main_net_inflow_ratio=flow.main_net_inflow_ratio if flow else None,
                    trigger_reason=(
                        f"{item.trigger_reason} 行业：{snapshot.industry or '未披露'}；"
                        "个股主力资金来自东方财富个股快照。"
                        if flow and flow.main_net_inflow is not None
                        else item.trigger_reason
                    ),
                )
            )
        if not has_verified_flow:
            return radar
        return replace(
            radar,
            source=f"{radar.source}+eastmoney_stock_flow",
            fast_movers=enriched,
            risks=[
                *radar.risks,
                "个股主力资金为逐股快照，不能替代全市场板块资金流。",
            ],
        )

    def _radar_tracked_symbols(self) -> list[str]:
        settings = load_runtime_settings().get("morning_radar")
        pool = self.memory_store.load_opportunity_pool() or {}
        symbols = [item["symbol"] for item in self.memory_store.load_watchlist()]
        symbols.extend(item["symbol"] for item in self.memory_store.load_portfolio()["positions"])
        symbols.extend(
            item["symbol"]
            for item in pool.get("candidates", [])
            if isinstance(item, dict) and isinstance(item.get("symbol"), str)
        )
        return list(dict.fromkeys(symbols))[: settings["fallback_maximum_symbols"]]

    def opportunity_pool(self) -> dict[str, Any]:
        pool = self.memory_store.load_opportunity_pool()
        return pool or {
            "pipeline_status": "not_run",
            "candidates": [],
            "excluded": [],
            "disclaimer": load_runtime_settings().get("opportunity_pipeline", "disclaimer"),
        }

    def scan_opportunities(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_symbols = payload.get("symbols", [])
        if not isinstance(raw_symbols, list) or any(not isinstance(item, str) for item in raw_symbols):
            raise ValueError("symbols must be an array of stock symbols")
        analysis_date = payload.get("analysis_date")
        if not isinstance(analysis_date, str) or not analysis_date:
            raise ValueError("analysis_date is required")
        maximum_level = _optional_int(payload.get("maximum_level")) or 3
        return self.opportunity_pipeline.run(
            analysis_date=analysis_date,
            explicit_symbols=raw_symbols,
            include_radar=payload.get("include_radar") is not False,
            maximum_level=maximum_level,
        )

    def replay_opportunity(self, payload: dict[str, Any]) -> dict[str, Any]:
        event_id = payload.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("event_id is required")
        return self.memory_store.replay_opportunity_run(event_id)

    def analyze(self, payload: dict[str, Any]) -> dict[str, Any]:
        symbol = payload.get("symbol")
        analysis_date = payload.get("analysis_date")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol is required")
        if not isinstance(analysis_date, str) or not analysis_date:
            raise ValueError("analysis_date is required")

        question = str(payload.get("question") or f"分析 {symbol}（{analysis_date}）")
        context = self.memory_store.build_context(symbol)
        realtime_quote: dict[str, object] | None = None
        quote = None
        if payload.get("include_realtime") is True:
            try:
                primary_quotes: dict[str, RealtimeQuote] = {}
                if self.stock_snapshot_client:
                    snapshot = self.stock_snapshot_client.fetch_snapshot(symbol)
                    snapshot_quote = snapshot.to_quote()
                    primary_quotes[normalize_symbol(symbol)] = snapshot_quote
                quote = self._complete_quotes([normalize_symbol(symbol)], primary_quotes)[normalize_symbol(symbol)]
                realtime_quote = quote.to_dict()
            except ValueError as exc:
                realtime_quote = {
                    "symbol": normalize_symbol(symbol),
                    "data_status": "unavailable",
                    "error": str(exc),
                }
            context["realtime_quote"] = realtime_quote
        report = self.workflow.run(
            symbol,
            analysis_date,
            trading_profile=self.memory_store.load_profile(),
            user_question=question,
            realtime_quote=realtime_quote,
        )
        if quote and report.name in {report.symbol, report.symbol.split(".")[0]} and quote.name:
            report = replace(report, name=quote.name)
        model_name = "deterministic-mvp"
        if payload.get("model_explain") is True or payload.get("deepseek_explain") is True:
            report = self.model_runtime.explain(
                report,
                context,
                expected_provider_id=_optional_string(payload.get("model_provider_id")),
                expected_model=_optional_string(payload.get("model_name")),
            )
            execution = report.model_execution or {}
            model_name = f"{execution.get('provider_id', 'unknown')}:{execution.get('model', 'unknown')}"

        event = self.memory_store.save_analysis(report, user_query=question, model_name=model_name)
        interaction = self.memory_store.save_interaction_summary(report, question, event.id)
        result = public_report_payload(report)
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
    user_apps: UserResearchAppPool | None = None
    test_sessions: TestAccessSessionRegistry | None = None
    research_capacity: ResearchCapacityGate | None = None
    team_test_config: dict[str, Any] | None = None

    def do_GET(self) -> None:  # noqa: N802
        route = self._route_path()
        if route == "/api/session":
            self._write_json(HTTPStatus.OK, self._session_payload())
            return
        if route == "/api/health":
            self._write_json(HTTPStatus.OK, self._health_payload())
            return
        session = self._require_test_session() if route.startswith("/api/") else None
        if route.startswith("/api/") and session is None:
            return
        app = self._app_for_session(session)
        if route == "/api/profile":
            self._write_json(HTTPStatus.OK, app.profile())
            return
        if route == "/api/tools":
            self._write_json(HTTPStatus.OK, {"tools": app.tools()})
            return
        if route == "/api/playbooks":
            self._write_json(HTTPStatus.OK, app.playbooks())
            return
        if route == "/api/watchlist":
            self._write_json(HTTPStatus.OK, app.watchlist())
            return
        if route == "/api/portfolio":
            self._write_json(HTTPStatus.OK, app.portfolio())
            return
        if route == "/api/models":
            self._write_json(HTTPStatus.OK, app.model_status())
            return
        if route == "/api/opportunities":
            self._write_json(HTTPStatus.OK, app.opportunity_pool())
            return
        self._serve_static(route)

    def do_POST(self) -> None:  # noqa: N802
        route = self._route_path()
        try:
            if route == "/api/session/login":
                self._login_test_session(self._read_json())
                return
            if route == "/api/session/logout":
                self._logout_test_session()
                return
            session = self._require_test_session()
            if session is None:
                return
            app = self._app_for_session(session)
            payload = self._read_json()
            if route == "/api/analyze":
                capacity = self._required_capacity_gate()
                with capacity.slot("analysis"):
                    result = app.analyze(payload)
                execution = result.get("model_execution")
                if isinstance(execution, dict) and execution.get("status") == "succeeded":
                    capacity.record_model_explanation()
                self._write_json(HTTPStatus.OK, result)
            elif route == "/api/feedback":
                self._write_json(HTTPStatus.OK, app.feedback(payload))
            elif route == "/api/playbook/activate":
                self._write_json(HTTPStatus.OK, app.activate_playbook(payload))
            elif route == "/api/watchlist":
                self._write_json(HTTPStatus.OK, app.add_watchlist(payload))
            elif route == "/api/watchlist/remove":
                self._write_json(HTTPStatus.OK, app.remove_watchlist(payload))
            elif route == "/api/portfolio/cash":
                self._write_json(HTTPStatus.OK, app.update_cash_balance(payload))
            elif route == "/api/portfolio/position":
                self._write_json(HTTPStatus.OK, app.upsert_position(payload))
            elif route == "/api/portfolio/position/remove":
                self._write_json(HTTPStatus.OK, app.remove_position(payload))
            elif route == "/api/market/refresh":
                self._write_json(HTTPStatus.OK, app.refresh_market())
            elif route == "/api/market/ticker":
                self._write_json(HTTPStatus.OK, app.refresh_ticker())
            elif route == "/api/morning/radar":
                self._write_json(HTTPStatus.OK, app.morning_radar(payload))
            elif route == "/api/opportunities/scan":
                with self._required_capacity_gate().slot("opportunity_scan"):
                    result = app.scan_opportunities(payload)
                self._write_json(HTTPStatus.OK, result)
            elif route == "/api/opportunities/replay":
                self._write_json(HTTPStatus.OK, app.replay_opportunity(payload))
            elif route == "/api/models/configure":
                if not self._browser_model_configuration_allowed():
                    self._write_json(
                        HTTPStatus.FORBIDDEN,
                        {"error": "小型团队测试模式不允许浏览器录入模型密钥，请由部署环境变量统一配置。"},
                    )
                elif not self._is_local_client():
                    self._write_json(HTTPStatus.FORBIDDEN, {"error": MODEL_CONFIG_LOCAL_ONLY_ERROR})
                else:
                    self._write_json(HTTPStatus.OK, app.configure_model(payload))
            elif route == "/api/models/clear":
                if not self._browser_model_configuration_allowed():
                    self._write_json(
                        HTTPStatus.FORBIDDEN,
                        {"error": "小型团队测试模式的模型密钥由部署环境变量管理，页面不能清除。"},
                    )
                elif not self._is_local_client():
                    self._write_json(HTTPStatus.FORBIDDEN, {"error": MODEL_CONFIG_LOCAL_ONLY_ERROR})
                else:
                    self._write_json(HTTPStatus.OK, app.clear_model_key(payload))
            elif route == "/api/memory/import":
                self._write_json(HTTPStatus.OK, {"added_events": app.import_memory(payload)})
            elif route == "/api/memory/export":
                self._write_json(
                    HTTPStatus.OK,
                    app.export_memory(),
                    headers={"Content-Disposition": 'attachment; filename="trading-agents-memory.json"'},
                )
            else:
                self._write_json(HTTPStatus.NOT_FOUND, {"error": "Unknown API route"})
        except TestAccessCapacityError as exc:
            self._write_json(
                HTTPStatus.TOO_MANY_REQUESTS,
                {"error": str(exc)},
                headers={"Retry-After": "5"},
            )
        except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:
            print(f"[web] unhandled {self.path}: {type(exc).__name__}: {exc}")
            self._write_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"error": "服务暂时不可用，已保留页面现有数据；请稍后重试。"},
            )

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 2_000_000:
            raise ValueError("Request body must be JSON and smaller than 2 MB")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _route_path(self) -> str:
        path = urlsplit(self.path).path
        return path.rstrip("/") or "/"

    def _is_local_client(self) -> bool:
        """Allow secret entry from this machine, never by client-controlled headers."""
        return _is_local_machine_address(self.client_address[0])

    def _health_payload(self) -> dict[str, Any]:
        payload = self.app.health()
        config = self.team_test_config or {}
        capacity = self.research_capacity.metrics() if self.research_capacity else {}
        payload.update(
            {
                "mode": "small_team_test" if config.get("enabled") else payload.get("mode", "local"),
                "real_data_only": bool(config.get("require_production_provider")),
                "test_access": {
                    "credential_validation": False,
                    "maximum_active_users": config.get("maximum_active_users"),
                    "active_users": self.test_sessions.active_user_count() if self.test_sessions else 0,
                    "browser_model_configuration": bool(config.get("allow_browser_model_configuration")),
                },
                "research_capacity": capacity,
            }
        )
        return payload

    def _session_payload(self, session: TestAccessSession | None = None) -> dict[str, Any]:
        session = session or self._current_test_session()
        config = self.team_test_config or {}
        return {
            "authenticated": session is not None,
            "test_mode": True,
            "credential_validation": False,
            "warning": "当前为小型测试访问：账号密码尚未校验，不能替代正式身份认证。",
            "user": session.public_payload() if session else None,
            "login_visual": load_runtime_settings().get("runtime", "login_visual"),
            "capacity": {
                "maximum_active_users": config.get("maximum_active_users"),
                "active_users": self.test_sessions.active_user_count() if self.test_sessions else 0,
                **(self.research_capacity.metrics() if self.research_capacity else {}),
            },
        }

    def _login_test_session(self, payload: dict[str, Any]) -> None:
        if self.test_sessions is None:
            self._write_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "测试会话服务未启用"})
            return
        session = self.test_sessions.login(
            payload.get("account"),
            payload.get("password"),
            bool(payload.get("remember")),
        )
        try:
            self._app_for_session(session)
        except Exception:
            self.test_sessions.logout(session.token)
            raise
        max_age = self.test_sessions.remaining_seconds(session)
        cookie = (
            f"{self._cookie_name()}={session.token}; Path=/; HttpOnly; SameSite=Lax; "
            f"Max-Age={max_age}"
        )
        if bool((self.team_test_config or {}).get("cookie_secure")):
            cookie += "; Secure"
        self._write_json(
            HTTPStatus.OK,
            self._session_payload(session),
            headers={"Set-Cookie": cookie},
        )

    def _logout_test_session(self) -> None:
        token = self._session_token()
        if self.test_sessions:
            self.test_sessions.logout(token)
        cookie = f"{self._cookie_name()}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
        if bool((self.team_test_config or {}).get("cookie_secure")):
            cookie += "; Secure"
        self._write_json(
            HTTPStatus.OK,
            {"authenticated": False, "test_mode": True},
            headers={"Set-Cookie": cookie},
        )

    def _require_test_session(self) -> TestAccessSession | None:
        if self.test_sessions is None:
            return None
        session = self._current_test_session()
        if session is None:
            self._write_json(
                HTTPStatus.UNAUTHORIZED,
                {"error": "测试会话不存在或已过期，请重新进入。", "login_required": True},
            )
        return session

    def _current_test_session(self) -> TestAccessSession | None:
        return self.test_sessions.resolve(self._session_token()) if self.test_sessions else None

    def _session_token(self) -> str | None:
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        cookie = SimpleCookie()
        try:
            cookie.load(raw)
        except Exception:
            return None
        value = cookie.get(self._cookie_name())
        return value.value if value else None

    def _cookie_name(self) -> str:
        return str((self.team_test_config or {}).get("cookie_name") or "tradingos_test_session")

    def _app_for_session(self, session: TestAccessSession | None) -> ResearchWebApp:
        if session is None or self.user_apps is None:
            return self.app
        return self.user_apps.get(session.user_id)  # type: ignore[return-value]

    def _required_capacity_gate(self) -> ResearchCapacityGate:
        if self.research_capacity is None:
            raise RuntimeError("研判容量门禁未初始化")
        return self.research_capacity

    def _browser_model_configuration_allowed(self) -> bool:
        return bool((self.team_test_config or {}).get("allow_browser_model_configuration"))

    def _serve_static(self, route: str | None = None) -> None:
        path_map = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/index.html": ("index.html", "text/html; charset=utf-8"),
            "/styles.css": ("styles.css", "text/css; charset=utf-8"),
            "/app.js": ("app.js", "application/javascript; charset=utf-8"),
        }
        target = path_map.get(route or self._route_path())
        if target is None:
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return
        filename, content_type = target
        body = (STATIC_DIR / filename).read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._send_security_headers(cache_control="no-store")
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
    settings = load_runtime_settings()
    server_config = settings.get("runtime", "local_server")
    team_config = settings.get("runtime", "small_team_test")
    if team_config["enabled"] and team_config["require_production_provider"] and provider_name != "production":
        raise RuntimeError("小型团队测试服务只允许 production Provider；样例数据仅用于离线回归测试")
    host = host or server_config["host"]
    port = port if port is not None else server_config["port"]
    memory_root = Path(memory_dir)
    memory_root.mkdir(parents=True, exist_ok=True)

    def build_app(root: Path) -> ResearchWebApp:
        return ResearchWebApp(
            LocalMemoryStore(root),
            workflow=build_production_workflow() if provider_name == "production" else build_sample_workflow(),
            stock_snapshot_client=EastmoneyStockSnapshotClient(),
            quote_cache=VerifiedDatasetCache(),
        )

    TradingDeskHandler.app = build_app(memory_root / "_system")
    TradingDeskHandler.user_apps = UserResearchAppPool(memory_root, build_app)
    TradingDeskHandler.test_sessions = TestAccessSessionRegistry(
        int(team_config["maximum_active_users"]),
        int(team_config["session_ttl_hours"]) * 60 * 60,
        int(team_config["remember_session_days"]) * 24 * 60 * 60,
    )
    TradingDeskHandler.research_capacity = ResearchCapacityGate(
        int(team_config["maximum_concurrent_research_jobs"])
    )
    TradingDeskHandler.team_test_config = dict(team_config)
    return ExclusiveThreadingHTTPServer((host, port), TradingDeskHandler)


def _build_sector_radar_fallback(provider: object) -> TushareIndustryRadarFallback | None:
    ranking = getattr(provider, "get_industry_flow_ranking", None)
    if not callable(ranking):
        return None
    return TushareIndustryRadarFallback(provider)  # type: ignore[arg-type]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the A-share research dashboard on the configured local or LAN interface.")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--memory-dir", default="data/memory")
    parser.add_argument("--provider", choices=["production", "sample"], default="production")
    args = parser.parse_args()
    try:
        server = create_server(args.host, args.port, args.memory_dir, args.provider)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE or getattr(exc, "winerror", None) == 10048:
            selected_port = args.port if args.port is not None else "配置端口"
            raise SystemExit(
                f"启动失败：端口 {selected_port} 已被其他进程占用。"
                "请先关闭旧的 TradingAgentsChina 实例，避免新旧后端随机响应。"
            ) from exc
        raise
    actual_host, actual_port = server.server_address[:2]
    if actual_host in {"0.0.0.0", "::"}:
        print(f"TradingAgentsChina is running locally at http://127.0.0.1:{actual_port}")
        print("LAN access is enabled. Use this computer's private IPv4 address with the same port on trusted networks only.")
    else:
        print(f"TradingAgentsChina is running at http://{actual_host}:{actual_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None


def _is_loopback_address(value: str) -> bool:
    try:
        return ip_address(value).is_loopback
    except ValueError:
        return False


def _is_local_machine_address(
    value: str, local_addresses: set[str] | frozenset[str] | None = None
) -> bool:
    """Recognize loopback and addresses assigned to the server itself.

    The decision uses the TCP peer address plus OS-resolved interface addresses;
    `Host`, `Origin`, and forwarding headers are intentionally ignored.
    """
    candidate = _normalized_ip(value)
    if candidate is None:
        return False
    if candidate.is_loopback:
        return True
    addresses = local_addresses if local_addresses is not None else _local_machine_addresses()
    return str(candidate) in {_normalized_ip_text(item) for item in addresses}


@lru_cache(maxsize=1)
def _local_machine_addresses() -> frozenset[str]:
    addresses = {"127.0.0.1", "::1"}
    hostnames = {socket.gethostname(), socket.getfqdn()}
    for hostname in hostnames:
        if not hostname:
            continue
        try:
            records = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        except OSError:
            continue
        for record in records:
            raw_address = str(record[4][0]).split("%", 1)[0]
            normalized = _normalized_ip(raw_address)
            if normalized is not None:
                addresses.add(str(normalized))
    return frozenset(addresses)


def _normalized_ip(value: str):
    try:
        parsed = ip_address(str(value).split("%", 1)[0])
    except ValueError:
        return None
    return getattr(parsed, "ipv4_mapped", None) or parsed


def _normalized_ip_text(value: str) -> str:
    parsed = _normalized_ip(value)
    return str(parsed) if parsed is not None else ""


def _optional_float(value: Any) -> float | None:
    return float(value) if value is not None else None


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def _usable_current_quote(quote: RealtimeQuote) -> bool:
    return quote_is_usable(quote)


def _unavailable_realtime_quote(symbol: str) -> RealtimeQuote:
    return RealtimeQuote(
        symbol=symbol,
        name=None,
        price=None,
        previous_close=None,
        change_pct=None,
        volume=None,
        amount=None,
        trade_date=None,
        trade_time=None,
        source="unavailable",
        data_status="unavailable",
        error="No current-day quote was returned by the configured real-time providers.",
    )


if __name__ == "__main__":
    main()
