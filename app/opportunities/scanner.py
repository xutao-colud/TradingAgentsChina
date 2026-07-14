from __future__ import annotations

from dataclasses import dataclass

from app.config.runtime import load_runtime_settings
from app.market.stock_snapshot import StockRealtimeSnapshot
from app.memory.models import TradingProfile
from app.opportunities.models import OpportunityCandidate, OpportunityEvidence
from app.schemas.report import MarketContext


@dataclass(frozen=True)
class CandidateObservation:
    snapshot: StockRealtimeSnapshot
    source_tags: list[str]
    radar_speed_pct: float | None = None
    radar_trigger: str | None = None


class OpportunityScanner:
    """Fast deterministic L1 scanner; it never calls an LLM."""

    def __init__(self) -> None:
        settings = load_runtime_settings()
        self.config = settings.get("opportunity_pipeline")
        self.bounds = settings.get("scoring", "score_bounds")

    def scan(
        self,
        observation: CandidateObservation,
        analysis_date: str,
        profile: TradingProfile,
        market_context: MarketContext,
        previous: OpportunityCandidate | None = None,
    ) -> OpportunityCandidate:
        snapshot = observation.snapshot
        level1 = self.config["level1"]
        coverage = self._coverage(snapshot)
        source_score = self._source_score(observation.source_tags)
        liquidity_score = self._liquidity_score(snapshot)
        capital_score = self._capital_score(snapshot)
        price_score = self._price_score(snapshot)
        profile_score = self._profile_score(snapshot, profile)
        components = {
            "source_priority": source_score,
            "data_coverage": self._bounded(coverage * self.bounds["max"]),
            "liquidity": liquidity_score,
            "capital_flow": capital_score,
            "price_behavior": price_score,
            "profile_fit": profile_score,
        }
        weighted = sum(
            components[name] * weight
            for name, weight in level1["component_weights"].items()
        )
        score = self._bounded(weighted)

        evidence = [
            OpportunityEvidence(
                source_id=f"opportunity-snapshot:{snapshot.symbol}:{snapshot.as_of}",
                title=f"{snapshot.symbol} lightweight market snapshot",
                source_type=snapshot.source,
                as_of=snapshot.as_of,
                facts=self._snapshot_facts(snapshot),
            ),
            OpportunityEvidence(
                source_id=f"opportunity-market:{analysis_date}",
                title="A-share market regime observed before candidate ranking",
                source_type="market_context",
                as_of=market_context.as_of or analysis_date,
                facts=[
                    f"regime={market_context.hot_money_cycle}",
                    f"data_status={market_context.data_status}",
                ],
            ),
        ]
        if observation.radar_trigger:
            evidence.append(
                OpportunityEvidence(
                    source_id=f"opportunity-radar:{snapshot.symbol}:{snapshot.as_of}",
                    title=f"{snapshot.symbol} verified radar observation",
                    source_type="eastmoney_push2_radar",
                    as_of=snapshot.as_of,
                    facts=[
                        observation.radar_trigger,
                        f"speed_pct={observation.radar_speed_pct}",
                    ],
                )
            )

        counterpoints, risks, invalidations = self._guardrails(snapshot, coverage, market_context)
        stage = self._lifecycle(score, coverage, previous)
        data_status = snapshot.data_status
        if coverage < level1["minimum_data_coverage"] or snapshot.data_status == "unavailable":
            data_status = "insufficient"

        return OpportunityCandidate(
            symbol=snapshot.symbol,
            name=snapshot.name,
            analysis_date=analysis_date,
            source_tags=sorted(set(observation.source_tags)),
            stage=stage,
            data_status=data_status,
            level1_score=score,
            data_coverage=round(coverage, 4),
            component_scores=components,
            evidence=evidence,
            counterpoints=counterpoints,
            risks=risks,
            invalidation_conditions=invalidations,
            profile_fit_score=profile_score,
        )

    def _coverage(self, snapshot: StockRealtimeSnapshot) -> float:
        required = self.config["level1"]["required_snapshot_fields"]
        present = sum(getattr(snapshot, field, None) is not None for field in required)
        return present / len(required) if required else 0.0

    def _source_score(self, source_tags: list[str]) -> int:
        priorities = self.config["source_priority"]
        scores = [priorities[tag] for tag in source_tags if tag in priorities]
        return self._bounded(max(scores) if scores else self.bounds["min"])

    def _liquidity_score(self, snapshot: StockRealtimeSnapshot) -> int:
        if snapshot.amount is None:
            return self.bounds["min"]
        full = self.config["level1"]["liquidity_full_amount"]
        return self._bounded(snapshot.amount / full * self.bounds["max"])

    def _capital_score(self, snapshot: StockRealtimeSnapshot) -> int:
        flow = snapshot.money_flow
        if flow is None:
            return self.bounds["min"]
        ratio = flow.main_net_inflow_ratio
        if ratio is not None:
            scale = self.config["level1"]["capital_flow_ratio_full_pct"]
            neutral = self.bounds["neutral"]
            return self._bounded(neutral + ratio / scale * neutral)
        if flow.main_net_inflow is None or snapshot.amount in (None, 0):
            return self.bounds["min"]
        neutral = self.bounds["neutral"]
        ratio_pct = flow.main_net_inflow / snapshot.amount * self.bounds["max"]
        scale = self.config["level1"]["capital_flow_ratio_full_pct"]
        return self._bounded(neutral + ratio_pct / scale * neutral)

    def _price_score(self, snapshot: StockRealtimeSnapshot) -> int:
        if snapshot.change_pct is None:
            return self.bounds["min"]
        preferred = self.config["level1"]["price_change_preferred_abs_pct"]
        maximum = self.config["level1"]["price_change_max_abs_pct"]
        change = snapshot.change_pct
        neutral = self.bounds["neutral"]
        quarter = (self.bounds["max"] - self.bounds["min"]) / 4
        if abs(change) <= preferred:
            return self._bounded(neutral + change / preferred * quarter)
        if change > preferred:
            excess_ratio = min(1.0, (change - preferred) / (maximum - preferred))
            return self._bounded(neutral + quarter * (1.0 - excess_ratio))
        return self._bounded(neutral - quarter - min(1.0, (abs(change) - preferred) / (maximum - preferred)) * quarter)

    def _profile_score(self, snapshot: StockRealtimeSnapshot, profile: TradingProfile) -> int:
        level1 = self.config["level1"]
        favorites = {item.strip().casefold() for item in profile.favorite_themes if item.strip()}
        if not favorites:
            return self._bounded(level1["profile_no_preference_score"])
        stock_tags = {
            item.strip().casefold()
            for item in [snapshot.industry or "", *snapshot.concepts]
            if item.strip()
        }
        if not stock_tags:
            return self._bounded(level1["profile_missing_data_score"])
        matched = any(
            favorite in tag or tag in favorite
            for favorite in favorites
            for tag in stock_tags
        )
        return self._bounded(
            level1["profile_theme_match_score"] if matched else level1["profile_theme_mismatch_score"]
        )

    def _snapshot_facts(self, snapshot: StockRealtimeSnapshot) -> list[str]:
        facts = [
            f"data_status={snapshot.data_status}",
            f"price={snapshot.price}",
            f"change_pct={snapshot.change_pct}",
            f"amount={snapshot.amount}",
            f"turnover_rate={snapshot.turnover_rate}",
            f"industry={snapshot.industry}",
        ]
        if snapshot.money_flow:
            facts.extend(
                [
                    f"main_net_inflow={snapshot.money_flow.main_net_inflow}",
                    f"main_net_inflow_ratio={snapshot.money_flow.main_net_inflow_ratio}",
                ]
            )
        return facts

    def _guardrails(
        self,
        snapshot: StockRealtimeSnapshot,
        coverage: float,
        market_context: MarketContext,
    ) -> tuple[list[str], list[str], list[str]]:
        counterpoints: list[str] = []
        risks: list[str] = [
            "L1 uses a lightweight snapshot and cannot replace announcement, fundamental, or long-history research.",
        ]
        invalidations = [
            "The market regime or source timestamp changes materially before deeper review.",
            "L2 data-readiness or evidence-chain gates fail.",
        ]
        minimum = self.config["level1"]["minimum_data_coverage"]
        if coverage < minimum:
            counterpoints.append(f"Snapshot coverage {coverage:.0%} is below the configured {minimum:.0%} gate.")
            risks.append("Missing snapshot fields prevent reliable cross-candidate comparison.")
        if snapshot.money_flow is None or snapshot.money_flow.main_net_inflow is None:
            counterpoints.append("No verified main-flow observation is available in the L1 snapshot.")
        elif snapshot.money_flow.main_net_inflow < 0:
            counterpoints.append("The latest observed main flow is negative.")
        maximum_change = self.config["level1"]["price_change_max_abs_pct"]
        if snapshot.change_pct is not None and abs(snapshot.change_pct) >= maximum_change:
            risks.append("The observed price move is extreme; chase/fall-continuation risk requires L2 review.")
        if market_context.data_status in set(self.config["market_blocking_statuses"]):
            risks.append("Market-wide context is not production-verified; L3 promotion is blocked.")
        return counterpoints, risks, invalidations

    def _lifecycle(
        self,
        score: int,
        coverage: float,
        previous: OpportunityCandidate | None,
    ) -> str:
        lifecycle = self.config["lifecycle"]
        if coverage < self.config["level1"]["minimum_data_coverage"] or score < lifecycle["eliminate_score"]:
            return "excluded"
        if previous and previous.level1_score - score >= lifecycle["retreat_drop"]:
            return "retreat"
        if score >= lifecycle["climax_score"]:
            return "climax"
        if score >= lifecycle["accelerate_score"]:
            return "accelerate"
        if score >= lifecycle["start_score"]:
            return "start"
        return "watch"

    def _bounded(self, value: float) -> int:
        return int(round(max(self.bounds["min"], min(self.bounds["max"], value))))

