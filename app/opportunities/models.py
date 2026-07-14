from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

from app.memory.models import utc_now_iso


@dataclass(frozen=True)
class OpportunityEvidence:
    source_id: str
    title: str
    source_type: str
    as_of: str
    facts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OpportunityCandidate:
    symbol: str
    name: str | None
    analysis_date: str
    source_tags: list[str]
    stage: str
    data_status: str
    level1_score: int
    data_coverage: float
    component_scores: dict[str, int]
    evidence: list[OpportunityEvidence]
    counterpoints: list[str]
    risks: list[str]
    invalidation_conditions: list[str]
    profile_fit_score: int | None = None
    research_score: int | None = None
    data_readiness_score: int | None = None
    evidence_chain_score: int | None = None
    promotion_score: int | None = None
    highest_completed_level: int = 1
    level2_analysis_event_id: str | None = None
    level3_analysis_event_id: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OpportunityCandidate":
        payload = dict(data)
        payload["evidence"] = [OpportunityEvidence(**item) for item in payload.get("evidence", [])]
        return cls(**payload)


@dataclass(frozen=True)
class OpportunityPoolRun:
    analysis_date: str
    market_regime: str
    market_data_status: str
    pipeline_status: str
    candidates: list[OpportunityCandidate]
    excluded: list[OpportunityCandidate]
    level_counts: dict[str, int]
    rule_version: str
    config_source: str
    disclaimer: str
    errors: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OpportunityPoolRun":
        payload = dict(data)
        payload["candidates"] = [OpportunityCandidate.from_dict(item) for item in payload.get("candidates", [])]
        payload["excluded"] = [OpportunityCandidate.from_dict(item) for item in payload.get("excluded", [])]
        return cls(**payload)

