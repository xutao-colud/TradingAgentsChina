from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from app.config.runtime import load_runtime_settings
from app.graph.state import ResearchState
from app.graph.workflow import AShareResearchWorkflow
from app.market.morning_radar import FastMover, MorningMoneyRadarClient, MorningRadarSnapshot
from app.market.stock_snapshot import (
    EastmoneyStockSnapshotClient,
    StockMoneyFlowBreakdown,
    StockRealtimeSnapshot,
)
from app.memory.local_store import LocalMemoryStore
from app.opportunities.models import OpportunityCandidate, OpportunityEvidence, OpportunityPoolRun
from app.opportunities.scanner import CandidateObservation, OpportunityScanner
from app.rules.trading_rules import normalize_symbol
from app.schemas.report import AnalysisReport, MarketContext


class OpportunityPipeline:
    """Market-first L1/L2/L3 pipeline with bounded deep-research work."""

    def __init__(
        self,
        workflow: AShareResearchWorkflow,
        memory_store: LocalMemoryStore,
        stock_snapshot_client: EastmoneyStockSnapshotClient | None = None,
        morning_radar_client: MorningMoneyRadarClient | None = None,
    ) -> None:
        self.workflow = workflow
        self.memory_store = memory_store
        self.stock_snapshot_client = stock_snapshot_client
        self.morning_radar_client = morning_radar_client
        self.scanner = OpportunityScanner()
        settings = load_runtime_settings()
        self.config = settings.get("opportunity_pipeline")
        self.settings = settings

    def run(
        self,
        analysis_date: str,
        explicit_symbols: Iterable[str] = (),
        include_radar: bool = True,
        maximum_level: int = 3,
        snapshots: dict[str, StockRealtimeSnapshot] | None = None,
        radar_snapshot: MorningRadarSnapshot | None = None,
    ) -> dict[str, object]:
        if maximum_level not in {1, 2, 3}:
            raise ValueError("maximum_level must be 1, 2, or 3")

        errors: list[str] = []
        market_context = self._market_context(analysis_date, errors)
        if market_context.data_status in set(self.config["degraded_data_statuses"]):
            errors.append(f"market_context: data_status={market_context.data_status}")
        radar = self._radar(include_radar, radar_snapshot, errors)
        source_map, radar_map = self._candidate_sources(explicit_symbols, radar)
        source_map = self._limit_universe(source_map)
        observed = self._load_snapshots(source_map, analysis_date, snapshots or {}, market_context, errors)

        previous = self._previous_candidates()
        candidates: list[OpportunityCandidate] = []
        for symbol, source_tags in source_map.items():
            snapshot = observed.get(symbol)
            if snapshot is None:
                continue
            mover = radar_map.get(symbol)
            candidates.append(
                self.scanner.scan(
                    CandidateObservation(
                        snapshot=snapshot,
                        source_tags=source_tags,
                        radar_speed_pct=mover.speed_pct if mover else None,
                        radar_trigger=mover.trigger_reason if mover else None,
                    ),
                    analysis_date,
                    self.memory_store.load_profile(),
                    market_context,
                    previous.get(symbol),
                )
            )

        candidates.sort(key=self._l1_sort_key, reverse=True)
        excluded = [item for item in candidates if item.stage == "excluded"]
        active = [item for item in candidates if item.stage != "excluded"][: self.config["level1"]["maximum_candidates"]]
        if maximum_level >= 2:
            active, level2_states = self._run_level2(active, analysis_date, errors)
        else:
            level2_states = {}
        if maximum_level >= 3:
            active = self._run_level3(active, level2_states, market_context, errors)

        active.sort(
            key=lambda item: (item.promotion_score if item.promotion_score is not None else item.level1_score),
            reverse=True,
        )
        errors = list(dict.fromkeys(errors))
        pipeline_status = "empty" if not active and not excluded else "partial" if errors else "completed"
        pool = OpportunityPoolRun(
            analysis_date=analysis_date,
            market_regime=market_context.hot_money_cycle,
            market_data_status=market_context.data_status,
            pipeline_status=pipeline_status,
            candidates=active,
            excluded=excluded,
            level_counts={
                "level1": len(active) + len(excluded),
                "level2": sum(item.highest_completed_level >= 2 for item in active),
                "level3": sum(item.highest_completed_level >= 3 for item in active),
            },
            rule_version=self.settings.rule_version,
            config_source=self.settings.source,
            disclaimer=self.config["disclaimer"],
            errors=errors,
        )
        memory_event = self.memory_store.save_opportunity_pool(pool.to_dict())
        return {**pool.to_dict(), "memory_event_id": memory_event.id}

    def _market_context(self, analysis_date: str, errors: list[str]) -> MarketContext:
        try:
            context = self.workflow.provider.get_market_context(analysis_date)
            provider_mode = getattr(self.workflow.provider, "data_mode", "production")
            return replace(context, data_status="sample", as_of=context.as_of or analysis_date) if provider_mode == "sample" else context
        except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"market_context: {exc}")
            return MarketContext(
                index_name="A-share market",
                index_change_pct=None,
                total_amount=None,
                advancers=None,
                decliners=None,
                limit_up_count=None,
                limit_down_count=None,
                hot_money_cycle="unknown",
                policy_themes=[],
                data_status="unavailable",
                as_of=analysis_date,
                unavailable_reasons=[str(exc)],
            )

    def _radar(
        self,
        include_radar: bool,
        supplied: MorningRadarSnapshot | None,
        errors: list[str],
    ) -> MorningRadarSnapshot | None:
        if not include_radar:
            return None
        radar = supplied
        if radar is None and self.morning_radar_client is not None:
            radar = self.morning_radar_client.fetch_snapshot()
        if radar is not None and radar.data_status not in set(self.config["admitted_radar_statuses"]):
            if radar.error:
                errors.append(f"morning_radar: {radar.error}")
            return None
        return radar

    def _candidate_sources(
        self,
        explicit_symbols: Iterable[str],
        radar: MorningRadarSnapshot | None,
    ) -> tuple[dict[str, list[str]], dict[str, FastMover]]:
        source_map: dict[str, list[str]] = {}

        def add(symbol: str, tag: str) -> None:
            normalized = normalize_symbol(symbol)
            source_map.setdefault(normalized, [])
            if tag not in source_map[normalized]:
                source_map[normalized].append(tag)

        for position in self.memory_store.load_portfolio()["positions"]:
            add(str(position["symbol"]), "position")
        for item in self.memory_store.load_watchlist():
            add(str(item["symbol"]), "watchlist")
        for symbol in explicit_symbols:
            add(str(symbol), "explicit")

        radar_map: dict[str, FastMover] = {}
        if radar is not None:
            for mover in radar.fast_movers:
                add(mover.symbol, "radar")
                radar_map[normalize_symbol(mover.symbol)] = mover
        return source_map, radar_map

    def _limit_universe(self, source_map: dict[str, list[str]]) -> dict[str, list[str]]:
        priorities = self.config["source_priority"]
        ordered = sorted(
            source_map.items(),
            key=lambda item: max((priorities.get(tag, 0) for tag in item[1]), default=0),
            reverse=True,
        )
        return dict(ordered[: self.config["level1"]["maximum_universe"]])

    def _load_snapshots(
        self,
        source_map: dict[str, list[str]],
        analysis_date: str,
        supplied: dict[str, StockRealtimeSnapshot],
        market_context: MarketContext,
        errors: list[str],
    ) -> dict[str, StockRealtimeSnapshot]:
        normalized_supplied = {normalize_symbol(symbol): item for symbol, item in supplied.items()}
        missing = [
            symbol
            for symbol in source_map
            if symbol not in normalized_supplied or normalized_supplied[symbol].data_status == "unavailable"
        ]
        if missing and self.stock_snapshot_client is not None:
            normalized_supplied.update(self.stock_snapshot_client.fetch_snapshots(missing))
            missing = [
                symbol
                for symbol in missing
                if symbol not in normalized_supplied or normalized_supplied[symbol].data_status == "unavailable"
            ]
        for symbol in missing:
            try:
                normalized_supplied[symbol] = self._snapshot_from_provider(symbol, analysis_date, market_context)
            except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
                errors.append(f"snapshot:{symbol}: {exc}")
        for symbol in source_map:
            snapshot = normalized_supplied.get(symbol)
            if snapshot is not None and snapshot.data_status in set(self.config["degraded_data_statuses"]):
                message = snapshot.error or f"data_status={snapshot.data_status}"
                errors.append(f"snapshot:{symbol}: {message}")
        return normalized_supplied

    def _snapshot_from_provider(
        self,
        symbol: str,
        analysis_date: str,
        market_context: MarketContext,
    ) -> StockRealtimeSnapshot:
        prices = self.workflow.provider.get_daily_prices(
            symbol,
            analysis_date,
            lookback_days=self.config["level2"]["provider_fallback_price_bars"],
        )
        profile = self.workflow.provider.get_stock_profile(symbol)
        flow = self.workflow.provider.get_money_flow(symbol, analysis_date)
        latest = prices[-1] if prices else None
        previous = prices[-2] if len(prices) >= 2 else None
        change_pct = None
        if latest is not None and previous is not None and previous.close:
            change_pct = round((latest.close / previous.close - 1) * 100, 4)
        money_flow = StockMoneyFlowBreakdown(
            trade_date=flow.as_of,
            main_net_inflow=flow.main_net_inflow,
            super_large_net_inflow=flow.super_large_net_inflow,
            large_net_inflow=flow.large_net_inflow,
            medium_net_inflow=flow.medium_net_inflow,
            small_net_inflow=flow.small_net_inflow,
            main_net_inflow_ratio=(flow.main_net_inflow / latest.amount * 100) if latest and latest.amount and flow.main_net_inflow is not None else None,
            visible_large_net_inflow=_sum_optional(flow.super_large_net_inflow, flow.large_net_inflow),
            hidden_follow_net_inflow=_sum_optional(flow.medium_net_inflow, flow.small_net_inflow),
        )
        return StockRealtimeSnapshot(
            symbol=symbol,
            name=profile.name,
            price=latest.close if latest else None,
            previous_close=previous.close if previous else None,
            change_pct=change_pct,
            open=latest.open if latest else None,
            high=latest.high if latest else None,
            low=latest.low if latest else None,
            volume=latest.volume if latest else None,
            amount=latest.amount if latest else None,
            turnover_rate=latest.turnover_rate if latest else None,
            market_cap=None,
            float_market_cap=None,
            industry=profile.industry,
            market_board=profile.board,
            region=None,
            concepts=profile.concepts,
            money_flow=money_flow,
            as_of=latest.trade_date if latest else analysis_date,
            source=type(self.workflow.provider).__name__,
            data_status="sample" if market_context.data_status == "sample" else "latest_available" if latest else "unavailable",
            error=None if latest else "Provider returned no daily prices",
        )

    def _run_level2(
        self,
        candidates: list[OpportunityCandidate],
        analysis_date: str,
        errors: list[str],
    ) -> tuple[list[OpportunityCandidate], dict[str, ResearchState]]:
        level1 = self.config["level1"]
        eligible = [
            item
            for item in candidates
            if item.level1_score >= level1["minimum_score_for_level2"]
            and item.data_coverage >= level1["minimum_data_coverage"]
        ][: self.config["level2"]["maximum_candidates"]]
        by_symbol = {item.symbol: item for item in candidates}
        states: dict[str, ResearchState] = {}
        for candidate in eligible:
            try:
                question = f"Evaluate {candidate.symbol} evidence and active-playbook fit for the opportunity pool."
                state = self.workflow.prepare_state(
                    candidate.symbol,
                    analysis_date,
                    trading_profile=self.memory_store.load_profile(),
                    user_question=question,
                )
                report = self.workflow.evaluate_state(state, include_committee=False)
                event = self.memory_store.save_analysis(
                    report,
                    user_query=question,
                    model_name="deterministic-level2",
                    metadata={"pipeline_level": 2, "opportunity_score": candidate.level1_score},
                )
                states[candidate.symbol] = state
                by_symbol[candidate.symbol] = self._attach_level2(candidate, report, event.id)
            except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
                errors.append(f"level2:{candidate.symbol}: {exc}")
                by_symbol[candidate.symbol] = replace(
                    candidate,
                    error=str(exc)[: self.config["level2"]["summary_limits"]["error_characters"]],
                )
        return [by_symbol[item.symbol] for item in candidates], states

    def _attach_level2(
        self,
        candidate: OpportunityCandidate,
        report: AnalysisReport,
        event_id: str,
    ) -> OpportunityCandidate:
        research = _insight_score(report, "decision")
        readiness = _insight_score(report, "data_quality")
        evidence_chain = _insight_score(report, "quality")
        profile_fit = _insight_score(report, "personalization", candidate.profile_fit_score)
        promotion = self._promotion_score(candidate.level1_score, research, evidence_chain, profile_fit)
        limits = self.config["level2"]["summary_limits"]
        return replace(
            candidate,
            research_score=research,
            data_readiness_score=readiness,
            evidence_chain_score=evidence_chain,
            profile_fit_score=profile_fit,
            promotion_score=promotion,
            highest_completed_level=2,
            level2_analysis_event_id=event_id,
            evidence=[
                *candidate.evidence,
                OpportunityEvidence(
                    source_id=f"analysis-event:{event_id}",
                    title=f"{candidate.symbol} deterministic L2 research",
                    source_type="local_analysis_memory",
                    as_of=report.analysis_date,
                    facts=[
                        f"research_score={research}",
                        f"data_readiness_score={readiness}",
                        f"evidence_chain_score={evidence_chain}",
                        f"profile_fit_score={profile_fit}",
                    ],
                ),
            ],
            counterpoints=list(dict.fromkeys([*candidate.counterpoints, *report.bear_case[: limits["counterpoints"]]])),
            risks=list(dict.fromkeys([*candidate.risks, *report.risk_factors[: limits["risks"]]])),
            invalidation_conditions=list(dict.fromkeys([*candidate.invalidation_conditions, *report.invalid_conditions[: limits["invalidation_conditions"]]])),
        )

    def _run_level3(
        self,
        candidates: list[OpportunityCandidate],
        states: dict[str, ResearchState],
        market_context: MarketContext,
        errors: list[str],
    ) -> list[OpportunityCandidate]:
        if market_context.data_status in set(self.config["market_blocking_statuses"]):
            return candidates
        gate = self.config["level3"]
        selected = [
            item
            for item in candidates
            if item.symbol in states
            and item.level1_score >= gate["minimum_level1_score"]
            and (item.data_readiness_score or 0) >= gate["minimum_data_readiness"]
            and (item.evidence_chain_score or 0) >= gate["minimum_evidence_chain"]
            and (item.research_score or 0) >= gate["minimum_research_score"]
        ]
        selected.sort(key=lambda item: item.promotion_score or 0, reverse=True)
        selected = selected[: gate["maximum_candidates"]]
        by_symbol = {item.symbol: item for item in candidates}
        for candidate in selected:
            try:
                state = states[candidate.symbol]
                self.workflow.convene_committee(state)
                report = self.workflow.build_report(state, analysis_level=3)
                event = self.memory_store.save_analysis(
                    report,
                    user_query=state.user_question,
                    model_name="deterministic-level3-court",
                    metadata={"pipeline_level": 3, "level2_event_id": candidate.level2_analysis_event_id},
                )
                by_symbol[candidate.symbol] = replace(
                    candidate,
                    highest_completed_level=3,
                    level3_analysis_event_id=event.id,
                    evidence=[
                        *candidate.evidence,
                        OpportunityEvidence(
                            source_id=f"analysis-event:{event.id}",
                            title=f"{candidate.symbol} L3 court review",
                            source_type="local_analysis_memory",
                            as_of=report.analysis_date,
                            facts=["court=evidence,cross-examination,risk-challenge,judge-summary"],
                        ),
                    ],
                )
            except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
                errors.append(f"level3:{candidate.symbol}: {exc}")
                by_symbol[candidate.symbol] = replace(
                    candidate,
                    error=str(exc)[: self.config["level2"]["summary_limits"]["error_characters"]],
                )
        return [by_symbol[item.symbol] for item in candidates]

    def _promotion_score(self, level1: int, research: int, evidence: int, profile: int) -> int:
        weights = self.config["ranking"]
        score = (
            level1 * weights["level1_weight"]
            + research * weights["research_weight"]
            + evidence * weights["evidence_weight"]
            + profile * weights["profile_weight"]
        )
        return int(round(score))

    def _previous_candidates(self) -> dict[str, OpportunityCandidate]:
        stored = self.memory_store.load_opportunity_pool()
        if not stored:
            return {}
        rows = [*stored.get("candidates", []), *stored.get("excluded", [])]
        return {
            item.symbol: item
            for row in rows
            if isinstance(row, dict)
            for item in [OpportunityCandidate.from_dict(row)]
        }

    def _l1_sort_key(self, candidate: OpportunityCandidate) -> tuple[int, float, int]:
        priorities = self.config["source_priority"]
        priority = max((priorities.get(tag, 0) for tag in candidate.source_tags), default=0)
        return candidate.level1_score, candidate.data_coverage, priority


def _insight_score(report: AnalysisReport, category: str, default: int | None = None) -> int:
    insight = next((item for item in report.skill_insights if item.category == category), None)
    if insight is not None:
        return insight.score
    return int(default or 0)


def _sum_optional(left: float | None, right: float | None) -> float | None:
    if left is None and right is None:
        return None
    return (left or 0.0) + (right or 0.0)
