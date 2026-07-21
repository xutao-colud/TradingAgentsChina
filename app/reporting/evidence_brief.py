from __future__ import annotations

from statistics import fmean
from typing import Any, Iterable

from app.config.runtime import load_runtime_settings
from app.reporting.presentation import present_value, role_label, judge_title
from app.schemas.report import AgentFinding, AnalysisReport, DataQualityReport, EvidenceSource, SkillInsight


def build_decision_brief(report: AnalysisReport) -> dict[str, Any]:
    """Build a compact, traceable argument without asking an LLM to invent one."""
    config = load_runtime_settings().get("reporting", "evidence_brief")
    neutral_score = float(config["neutral_score"])
    source_map = {source.id: source for source in report.evidence_sources}
    traceable = [finding for finding in report.agent_findings if _resolved_sources(finding, source_map)]
    ranked = sorted(
        traceable,
        key=lambda item: (abs(item.score - neutral_score) * item.confidence, item.confidence),
        reverse=True,
    )
    decisive_findings = ranked[: int(config["maximum_decisive_evidence"])]
    decisive = [
        _finding_claim(finding, source_map, neutral_score, config)
        for finding in decisive_findings
    ]
    counter = _counter_evidence(traceable, decisive_findings, source_map, neutral_score, config)
    committee = _committee_summary(report.skill_insights)
    invalidations = _invalidation_conditions(report, decisive_findings, committee, config)
    profile_fit = _profile_summary(report.skill_insights, config)
    gaps = _critical_data_gaps(report, config)
    return present_value({
        "version": config["version"],
        "headline": f"当前证据形成“{report.conclusion}”裁决",
        "thesis": (
            f"市场状态为“{report.market_regime}”，风险等级为“{report.risk_level}”。"
            f"行动框架：{report.action_plan}"
        ),
        "data_boundary": {
            "status": report.data_status,
            "analysis_date": report.analysis_date,
            "evidence_source_count": len(report.evidence_sources),
            "traceable_finding_count": len(traceable),
            "total_finding_count": len(report.agent_findings),
            "confidence": report.confidence,
        },
        "decisive_evidence": decisive,
        "strongest_counter_evidence": counter,
        "invalidation_conditions": invalidations,
        "court": committee,
        "profile_fit": profile_fit,
        "critical_data_gaps": gaps,
        "disclaimer": report.disclaimer,
    })


def build_compact_model_payload(report: AnalysisReport) -> dict[str, Any]:
    """Keep model context focused on accepted evidence rather than the full report dump."""
    config = load_runtime_settings().get("reporting", "evidence_brief")
    maximum_findings = int(config["maximum_model_findings"])
    maximum_observations = int(config["maximum_observations_per_claim"])
    findings = sorted(
        report.agent_findings,
        key=lambda item: (item.confidence, abs(item.score - float(config["neutral_score"]))),
        reverse=True,
    )[:maximum_findings]
    return present_value({
        "identity": {
            "symbol": report.symbol,
            "name": report.name,
            "analysis_date": report.analysis_date,
            "user_question": report.user_question,
        },
        "deterministic_result": {
            "data_status": report.data_status,
            "market_regime": report.market_regime,
            "conclusion": report.conclusion,
            "risk_level": report.risk_level,
            "confidence": report.confidence,
            "action_plan": report.action_plan,
            "scores": {
                "fundamental": report.fundamental_score,
                "technical": report.technical_score,
                "capital_flow": report.capital_flow_score,
                "announcement": report.sentiment_score,
                "theme": report.theme_score,
            },
        },
        "decision_brief": report.decision_brief,
        "findings": [
            {
                "agent": role_label(item.agent),
                "conclusion": item.conclusion,
                "score": item.score,
                "confidence": item.confidence,
                "evidence": item.evidence[:maximum_observations],
                "counterpoints": item.counterpoints[:maximum_observations],
                "risks": item.risks[:maximum_observations],
                "invalidation_conditions": item.invalidation_conditions[:maximum_observations],
                "source_ids": item.source_ids,
            }
            for item in findings
        ],
        "evidence_sources": [
            {
                "id": source.id,
                "title": source.title,
                "source_type": source.source_type,
                "as_of": source.as_of,
            }
            for source in report.evidence_sources
        ],
        "safety_boundary": report.disclaimer,
    })


def compact_memory_context(memory_context: dict[str, Any]) -> dict[str, Any]:
    config = load_runtime_settings().get("reporting", "evidence_brief")
    maximum = int(config["maximum_model_memory_items"])
    return {
        "trading_profile": memory_context.get("trading_profile", {}),
        "recent_same_symbol_reports": [
            _compact_memory_item(item) for item in memory_context.get("recent_same_symbol_reports", [])[-maximum:]
        ],
        "recent_same_symbol_feedback": [
            _compact_memory_item(item) for item in memory_context.get("recent_same_symbol_feedback", [])[-maximum:]
        ],
    }


def _finding_claim(
    finding: AgentFinding,
    source_map: dict[str, EvidenceSource],
    neutral_score: float,
    config: dict[str, Any],
) -> dict[str, Any]:
    return {
        "domain": role_label(finding.agent),
        "direction": "支持" if finding.score >= neutral_score else "约束",
        "claim": finding.conclusion,
        "score": finding.score,
        "confidence": finding.confidence,
        "observations": finding.evidence[: int(config["maximum_observations_per_claim"])],
        "sources": _source_payloads(finding.source_ids, source_map, config),
    }


def _counter_evidence(
    findings: list[AgentFinding],
    decisive_findings: list[AgentFinding],
    source_map: dict[str, EvidenceSource],
    neutral_score: float,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    maximum = int(config["maximum_counter_evidence"])
    if not findings:
        return []
    evidence_direction = fmean(item.score for item in findings) >= neutral_score
    opponents = [item for item in findings if (item.score < neutral_score) == evidence_direction]
    opponents.sort(key=lambda item: item.score, reverse=not evidence_direction)
    selected: list[dict[str, Any]] = []
    for finding in opponents:
        selected.append({
            **_finding_claim(finding, source_map, neutral_score, config),
            "why_it_matters": (finding.counterpoints or finding.risks or finding.invalidation_conditions or [
                "该维度与当前主要证据方向相反，需要独立复核。"
            ])[0],
        })
        if len(selected) >= maximum:
            return selected
    for finding in decisive_findings:
        if not finding.counterpoints:
            continue
        selected.append({
            "domain": role_label(finding.agent),
            "direction": "反证",
            "claim": finding.counterpoints[0],
            "score": finding.score,
            "confidence": finding.confidence,
            "observations": finding.risks[: int(config["maximum_observations_per_claim"])],
            "sources": _source_payloads(finding.source_ids, source_map, config),
            "why_it_matters": "该限制直接约束本维度结论的外推范围。",
        })
        if len(selected) >= maximum:
            break
    return selected


def _committee_summary(insights: list[SkillInsight]) -> dict[str, Any]:
    committee = next((item for item in insights if item.category == "committee"), None)
    if committee is None:
        return {"status": "not_run", "verdict": "本次未召开投资流派委员会。"}
    details = committee.details if isinstance(committee.details, dict) else {}
    judge = details.get("judge") if isinstance(details.get("judge"), dict) else {}
    factions = details.get("factions") if isinstance(details.get("factions"), list) else []
    status = "decided" if factions else "refused"
    return {
        "status": status,
        "role_label": judge_title(),
        "winner": judge.get("winner"),
        "winner_route": judge.get("winner_route"),
        "runner_up": judge.get("runner_up"),
        "score_gap": judge.get("score_gap"),
        "reliability": judge.get("reliability"),
        "verdict": judge.get("verdict") or committee.conclusion,
        "action": judge.get("action") or committee.strategy,
        "reason": list(judge.get("reason") or [])[:3],
        "score_warning": judge.get("score_warning"),
        "winner_invalid_if": list((factions[0] if factions else {}).get("invalid_if") or []),
    }


def _profile_summary(insights: list[SkillInsight], config: dict[str, Any]) -> dict[str, Any] | None:
    insight = next((item for item in insights if item.category == "personalization"), None)
    if insight is None:
        return None
    maximum = int(config["maximum_observations_per_claim"])
    return {
        "stage": insight.stage,
        "conclusion": insight.conclusion,
        "strategy": insight.strategy,
        "evidence": insight.evidence[:maximum],
        "risks": insight.risks[:maximum],
    }


def _invalidation_conditions(
    report: AnalysisReport,
    decisive_findings: list[AgentFinding],
    committee: dict[str, Any],
    config: dict[str, Any],
) -> list[str]:
    values: list[str] = list(report.invalid_conditions)
    for finding in decisive_findings:
        values.extend(finding.invalidation_conditions)
    values.extend(committee.get("winner_invalid_if") or [])
    return _dedupe(values)[: int(config["maximum_invalidation_conditions"])]


def _critical_data_gaps(report: AnalysisReport, config: dict[str, Any]) -> list[dict[str, Any]]:
    status_priority = {"failed": 0, "warning": 1, "passed": 2}
    quality = sorted(
        (item for item in report.data_quality_reports if not item.dataset.startswith("raw:")),
        key=lambda item: (not item.blocking, status_priority.get(item.status, 3), item.valid_records > 0, item.dataset),
    )
    maximum = int(config["maximum_critical_data_gaps"])
    maximum_characters = int(config["maximum_gap_characters"])
    gaps: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in quality:
        if item.status == "passed":
            continue
        key = f"{item.provider}.{item.dataset}"
        if key in seen:
            continue
        seen.add(key)
        issue = item.issues[0].message if item.issues else "该数据集未通过质量审查。"
        gaps.append({
            "dataset": key,
            "status": item.status,
            "blocking": item.blocking,
            "as_of": item.as_of,
            "reason": _truncate(issue, maximum_characters),
        })
        if len(gaps) >= maximum:
            return gaps
    readiness = next((item for item in report.skill_insights if item.category == "data_quality"), None)
    for risk in readiness.risks if readiness else []:
        normalized = risk.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        gaps.append({
            "dataset": "data_readiness",
            "status": report.data_status,
            "blocking": True,
            "as_of": report.analysis_date,
            "reason": _truncate(normalized, maximum_characters),
        })
        if len(gaps) >= maximum:
            break
    return gaps


def _source_payloads(
    source_ids: list[str],
    source_map: dict[str, EvidenceSource],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    maximum = int(config["maximum_sources_per_claim"])
    return [
        {
            "id": source.id,
            "title": source.title,
            "source_type": source.source_type,
            "as_of": source.as_of,
        }
        for source_id in source_ids
        if (source := source_map.get(source_id)) is not None
    ][:maximum]


def _resolved_sources(finding: AgentFinding, source_map: dict[str, EvidenceSource]) -> list[EvidenceSource]:
    return [source_map[source_id] for source_id in finding.source_ids if source_id in source_map]


def _dedupe(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _truncate(value: str, maximum: int) -> str:
    normalized = " ".join(value.split())
    return normalized if len(normalized) <= maximum else normalized[: maximum - 1].rstrip() + "…"


def _compact_memory_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"summary": str(item)}
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else item
    report = payload.get("report") if isinstance(payload.get("report"), dict) else payload
    return {
        "created_at": item.get("created_at"),
        "symbol": report.get("symbol"),
        "analysis_date": report.get("analysis_date"),
        "conclusion": report.get("conclusion"),
        "market_regime": report.get("market_regime"),
        "risk_level": report.get("risk_level"),
        "user_comment": payload.get("user_comment"),
        "feedback_type": payload.get("feedback_type"),
    }
