from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.memory.models import FeedbackEvent, MemoryEvent, TradingProfile
from app.playbooks.catalog import get_playbook
from app.rules.trading_rules import normalize_symbol
from app.saas.contracts import StrategyOutcomeRecord
from app.schemas.report import AnalysisReport


class LocalMemoryStore:
    def __init__(self, root: str | Path = "data/memory") -> None:
        self.root = Path(root)
        self.profile_path = self.root / "trading_profile.json"
        self.analysis_path = self.root / "analysis_events.jsonl"
        self.feedback_path = self.root / "feedback_events.jsonl"
        self.interaction_path = self.root / "interaction_events.jsonl"
        self.watchlist_path = self.root / "watchlist.json"
        self.portfolio_path = self.root / "portfolio.json"

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def load_profile(self) -> TradingProfile:
        self.ensure()
        if not self.profile_path.exists():
            profile = TradingProfile()
            self.save_profile(profile)
            return profile
        data = json.loads(self.profile_path.read_text(encoding="utf-8"))
        return TradingProfile.from_dict(data)

    def save_profile(self, profile: TradingProfile) -> None:
        self.ensure()
        self.profile_path.write_text(
            json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def set_active_playbook(self, playbook_id: str) -> TradingProfile:
        get_playbook(playbook_id)
        profile = self.load_profile()
        if profile.active_playbook == playbook_id:
            return profile
        updated = TradingProfile(
            style=profile.style,
            risk_level=profile.risk_level,
            holding_period=profile.holding_period,
            preferred_setups=profile.preferred_setups,
            avoid_patterns=profile.avoid_patterns,
            favorite_themes=profile.favorite_themes,
            review_rules=profile.review_rules,
            active_playbook=playbook_id,
            version=profile.version + 1,
        )
        self.save_profile(updated)
        return updated

    def load_watchlist(self) -> list[dict[str, Any]]:
        self.ensure()
        if not self.watchlist_path.exists():
            return []
        data = json.loads(self.watchlist_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("Watchlist storage is invalid")
        return data

    def add_watchlist(self, symbol: str, note: str | None = None) -> list[dict[str, Any]]:
        normalized = normalize_symbol(symbol)
        items = self.load_watchlist()
        existing = next((item for item in items if item.get("symbol") == normalized), None)
        if existing is None:
            items.append({"symbol": normalized, "note": (note or "").strip()[:120]})
        elif note is not None:
            existing["note"] = note.strip()[:120]
        self._write_json(self.watchlist_path, items)
        return items

    def remove_watchlist(self, symbol: str) -> list[dict[str, Any]]:
        normalized = normalize_symbol(symbol)
        items = [item for item in self.load_watchlist() if item.get("symbol") != normalized]
        self._write_json(self.watchlist_path, items)
        return items

    def load_portfolio(self) -> dict[str, Any]:
        self.ensure()
        default = {"currency": "CNY", "cash_balance": 0.0, "positions": []}
        if not self.portfolio_path.exists():
            self._write_json(self.portfolio_path, default)
            return default
        data = json.loads(self.portfolio_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("positions", []), list):
            raise ValueError("Portfolio storage is invalid")
        return {**default, **data}

    def set_cash_balance(self, cash_balance: float) -> dict[str, Any]:
        if cash_balance < 0:
            raise ValueError("cash_balance must be non-negative")
        portfolio = self.load_portfolio()
        portfolio["cash_balance"] = round(float(cash_balance), 2)
        self._write_json(self.portfolio_path, portfolio)
        return portfolio

    def upsert_position(self, symbol: str, quantity: float, cost_price: float) -> dict[str, Any]:
        if quantity <= 0 or cost_price < 0:
            raise ValueError("quantity must be positive and cost_price must be non-negative")
        normalized = normalize_symbol(symbol)
        portfolio = self.load_portfolio()
        positions = portfolio["positions"]
        new_position = {"symbol": normalized, "quantity": float(quantity), "cost_price": round(float(cost_price), 4)}
        for index, position in enumerate(positions):
            if position.get("symbol") == normalized:
                positions[index] = new_position
                break
        else:
            positions.append(new_position)
        self._write_json(self.portfolio_path, portfolio)
        return portfolio

    def remove_position(self, symbol: str) -> dict[str, Any]:
        normalized = normalize_symbol(symbol)
        portfolio = self.load_portfolio()
        portfolio["positions"] = [item for item in portfolio["positions"] if item.get("symbol") != normalized]
        self._write_json(self.portfolio_path, portfolio)
        return portfolio

    def save_analysis(self, report: AnalysisReport, user_query: str | None = None, model_name: str | None = None) -> MemoryEvent:
        profile = self.load_profile()
        event = MemoryEvent(
            event_type="analysis_report",
            symbol=report.symbol,
            analysis_date=report.analysis_date,
            payload={
                "user_query": user_query,
                "model_name": model_name,
                "profile_version": profile.version,
                "report": report.to_dict(),
            },
        )
        self._append_jsonl(self.analysis_path, event.to_dict())
        return event

    def save_interaction_summary(
        self,
        report: AnalysisReport,
        question: str,
        analysis_event_id: str | None = None,
    ) -> MemoryEvent:
        """Persist a compact, portable summary of one research question and answer."""
        alignment = next(
            (item for item in report.skill_insights if item.category == "personalization"),
            None,
        )
        event = MemoryEvent(
            event_type="interaction_summary",
            symbol=report.symbol,
            analysis_date=report.analysis_date,
            payload={
                "question": question,
                "analysis_event_id": analysis_event_id,
                "summary": {
                    "conclusion": report.conclusion,
                    "risk_level": report.risk_level,
                    "action_plan": report.action_plan,
                    "market_regime": report.market_regime,
                    "risk_factors": report.risk_factors[:3],
                    "profile_fit": alignment.stage if alignment else None,
                },
            },
        )
        self._append_jsonl(self.interaction_path, event.to_dict())
        return event

    def record_feedback(self, feedback: FeedbackEvent) -> FeedbackEvent:
        self.ensure()
        self._append_jsonl(self.feedback_path, feedback.to_dict())
        self._apply_explicit_feedback(feedback)
        return feedback

    def recent_analyses(self, symbol: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
        rows = self._read_jsonl(self.analysis_path)
        if symbol:
            rows = [row for row in rows if row.get("symbol") == symbol]
        return rows[-limit:]

    def recent_interactions(self, symbol: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
        rows = self._read_jsonl(self.interaction_path)
        if symbol:
            rows = [row for row in rows if row.get("symbol") == symbol]
        return rows[-limit:]

    def local_strategy_outcomes(
        self,
        aggregate_consent: bool = False,
        tenant_id: str = "local",
        user_id: str = "local-user",
    ) -> list[StrategyOutcomeRecord]:
        """Adapt manual outcome feedback into future SaaS outcome contracts.

        Account balances and position snapshots are intentionally excluded. The
        caller must explicitly opt in before these records can be aggregated.
        """
        reports = {item["id"]: item for item in self._read_jsonl(self.analysis_path)}
        outcomes: list[StrategyOutcomeRecord] = []
        for feedback in self._read_jsonl(self.feedback_path):
            if feedback.get("feedback_type") != "outcome" or feedback.get("outcome_return_pct") is None:
                continue
            report_id = feedback.get("analysis_report_id")
            report_event = reports.get(report_id)
            if not isinstance(report_id, str) or not report_event:
                continue
            report = report_event.get("payload", {}).get("report", {})
            playbook_id = report.get("active_playbook")
            if not isinstance(playbook_id, str):
                continue
            fit_score = next(
                (
                    item.get("score")
                    for item in report.get("skill_insights", [])
                    if item.get("category") == "playbook" and isinstance(item.get("score"), int)
                ),
                0,
            )
            outcome_days = feedback.get("outcome_days")
            if not isinstance(outcome_days, int) or outcome_days <= 0:
                continue
            outcomes.append(
                StrategyOutcomeRecord(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    analysis_report_id=report_id,
                    playbook_id=playbook_id,
                    playbook_fit_score=fit_score,
                    outcome_return_pct=float(feedback["outcome_return_pct"]),
                    outcome_days=outcome_days,
                    aggregate_consent=aggregate_consent,
                    outcome_source="manual",
                    id=str(feedback.get("id")),
                    created_at=str(feedback.get("created_at")),
                )
            )
        return outcomes

    def build_context(self, symbol: str, limit: int = 3) -> dict[str, Any]:
        profile = self.load_profile()
        recent = self.recent_analyses(symbol=symbol, limit=limit)
        interactions = self.recent_interactions(symbol=symbol, limit=limit)
        return {
            "trading_profile": profile.to_dict(),
            "recent_same_symbol_reports": [
                {
                    "id": item["id"],
                    "created_at": item["created_at"],
                    "analysis_date": item.get("analysis_date"),
                    "conclusion": item["payload"]["report"].get("conclusion"),
                    "risk_level": item["payload"]["report"].get("risk_level"),
                }
                for item in recent
            ],
            "recent_same_symbol_feedback": [
                {
                    "id": item["id"],
                    "feedback_type": item["feedback_type"],
                    "user_comment": item["user_comment"],
                    "learned_rule": item.get("learned_rule"),
                }
                for item in self._recent_feedback(symbol=symbol, limit=limit)
            ],
            "recent_same_symbol_interactions": [
                {
                    "id": item["id"],
                    "created_at": item["created_at"],
                    "question": item["payload"].get("question"),
                    "summary": item["payload"].get("summary", {}),
                }
                for item in interactions
            ],
        }

    def export_bundle(self, destination: str | Path | None = None) -> dict[str, Any]:
        """Return or write a self-contained portable profile and append-only history."""
        bundle = {
            "format": "trading-agents-china-memory",
            "version": 1,
            "trading_profile": self.load_profile().to_dict(),
            "events": {
                "analysis": self._read_jsonl(self.analysis_path),
                "feedback": self._read_jsonl(self.feedback_path),
                "interaction": self._read_jsonl(self.interaction_path),
            },
            "watchlist": self.load_watchlist(),
            "portfolio": self.load_portfolio(),
        }
        if destination is not None:
            path = Path(destination)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        return bundle

    def import_bundle(self, source: str | Path | dict[str, Any]) -> dict[str, int]:
        """Merge a portable bundle by event id; existing local events are never overwritten."""
        if isinstance(source, (str, Path)):
            data = json.loads(Path(source).read_text(encoding="utf-8"))
        else:
            data = source
        if data.get("format") != "trading-agents-china-memory" or data.get("version") != 1:
            raise ValueError("Unsupported memory bundle format")
        profile_data = data.get("trading_profile")
        events = data.get("events")
        if not isinstance(profile_data, dict) or not isinstance(events, dict):
            raise ValueError("Memory bundle is missing profile or events")

        imported_profile = TradingProfile.from_dict(profile_data)
        current_profile = self.load_profile()
        if imported_profile.version >= current_profile.version:
            self.save_profile(imported_profile)

        counts = {
            "analysis": self._merge_event_rows(self.analysis_path, events.get("analysis", [])),
            "feedback": self._merge_event_rows(self.feedback_path, events.get("feedback", [])),
            "interaction": self._merge_event_rows(self.interaction_path, events.get("interaction", [])),
        }
        watchlist = data.get("watchlist")
        if watchlist is not None:
            if not isinstance(watchlist, list):
                raise ValueError("Memory bundle watchlist must be an array")
            for item in watchlist:
                if not isinstance(item, dict) or not isinstance(item.get("symbol"), str):
                    raise ValueError("Memory bundle contains an invalid watchlist item")
                self.add_watchlist(item["symbol"], str(item.get("note", "")))
        portfolio = data.get("portfolio")
        if portfolio is not None:
            if not isinstance(portfolio, dict):
                raise ValueError("Memory bundle portfolio must be an object")
            self._write_json(self.portfolio_path, portfolio)
        return counts

    def save_external_analysis(
        self,
        symbol: str,
        analysis_date: str,
        report: dict[str, Any],
        user_query: str | None = None,
    ) -> MemoryEvent:
        """Store an MCP-supplied normalized report without trusting it as instructions."""
        profile = self.load_profile()
        event = MemoryEvent(
            event_type="analysis_report",
            symbol=symbol,
            analysis_date=analysis_date,
            payload={
                "user_query": user_query,
                "model_name": "external-mcp-client",
                "profile_version": profile.version,
                "report": report,
            },
        )
        self._append_jsonl(self.analysis_path, event.to_dict())
        return event

    def _append_jsonl(self, path: Path, row: dict[str, Any]) -> None:
        self.ensure()
        with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _write_json(self, path: Path, data: Any) -> None:
        self.ensure()
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows

    def _merge_event_rows(self, path: Path, imported_rows: Any) -> int:
        if not isinstance(imported_rows, list):
            raise ValueError("Memory bundle event collections must be arrays")
        existing_ids = {row.get("id") for row in self._read_jsonl(path)}
        added = 0
        for row in imported_rows:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                raise ValueError("Memory bundle contains an invalid event")
            if row["id"] not in existing_ids:
                self._append_jsonl(path, row)
                existing_ids.add(row["id"])
                added += 1
        return added

    def _recent_feedback(self, symbol: str, limit: int) -> list[dict[str, Any]]:
        rows = [item for item in self._read_jsonl(self.feedback_path) if item.get("symbol") == symbol]
        return rows[-limit:]

    def _apply_explicit_feedback(self, feedback: FeedbackEvent) -> None:
        """Apply only explicit preference/rule feedback; outcomes remain evidence, not preferences."""
        profile = self.load_profile()
        preferred = list(profile.preferred_setups)
        avoid = list(profile.avoid_patterns)
        rules = list(profile.review_rules)
        changed = False
        comment = feedback.user_comment.replace(" ", "")

        if feedback.feedback_type == "preference":
            if any(term in comment for term in ("低吸", "回踩")):
                changed |= _append_unique(preferred, "趋势回踩")
            if any(term in comment for term in ("不追高", "不喜欢追高", "避免追高")):
                changed |= _append_unique(avoid, "追高")
            if any(term in comment for term in ("不要ST", "不做ST", "避开ST")):
                changed |= _append_unique(avoid, "ST/*ST")

        if feedback.feedback_type == "rule" and feedback.learned_rule:
            changed |= _append_unique(rules, feedback.learned_rule)

        if changed:
            self.save_profile(
                TradingProfile(
                    style=profile.style,
                    risk_level=profile.risk_level,
                    holding_period=profile.holding_period,
                    preferred_setups=preferred,
                    avoid_patterns=avoid,
                    favorite_themes=profile.favorite_themes,
                    review_rules=rules,
                    active_playbook=profile.active_playbook,
                    version=profile.version + 1,
                )
            )


def _append_unique(items: list[str], value: str) -> bool:
    if value in items:
        return False
    items.append(value)
    return True
