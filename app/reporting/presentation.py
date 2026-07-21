from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Mapping

from app.config.runtime import load_runtime_settings
from app.schemas.report import AgentFinding, AnalysisReport, SkillInsight


def role_label(agent_id: str) -> str:
    """Return a public research role without changing the stable internal id."""
    config = _config()
    return str(config["finding_roles"].get(agent_id) or present_text(agent_id))


def present_text(value: str) -> str:
    """Translate internal implementation vocabulary in human-readable text."""
    config = _config()
    result = value
    replacements = {
        **config.get("phrase_replacements", {}),
        **config["finding_roles"],
    }
    for source, target in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        result = result.replace(str(source), str(target))
    result = re.sub(
        r"(?<![A-Za-z])Judge(?![A-Za-z])",
        str(config["judge_title"]),
        result,
    )
    result = re.sub(
        r"(?<![A-Za-z])Agent(?![A-Za-z])",
        str(config["generic_agent_label"]),
        result,
    )
    return result


def present_value(value: Any) -> Any:
    """Translate string values recursively while preserving structured keys."""
    if isinstance(value, str):
        return present_text(value)
    if isinstance(value, Mapping):
        return {key: present_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [present_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(present_value(item) for item in value)
    return value


def public_report_payload(report: AnalysisReport) -> dict[str, Any]:
    """Create the user-facing report payload; never mutate the auditable report."""
    payload = present_value(report.to_dict())
    for finding in payload.get("agent_findings", []):
        if isinstance(finding, dict):
            finding["agent"] = role_label(str(finding.get("agent", "")))
    _inject_judge_role(payload.get("skill_insights", []))
    court = payload.get("decision_brief", {}).get("court")
    if isinstance(court, dict):
        court.setdefault("role_label", str(_config()["judge_title"]))
    return payload


def present_analysis_report(report: AnalysisReport) -> AnalysisReport:
    """Return a presentation-only copy for Markdown and other renderers."""
    findings = [
        replace(
            finding,
            agent=role_label(finding.agent),
            conclusion=present_text(finding.conclusion),
            evidence=list(present_value(finding.evidence)),
            risks=list(present_value(finding.risks)),
            counterpoints=list(present_value(finding.counterpoints)),
            invalidation_conditions=list(present_value(finding.invalidation_conditions)),
            details=dict(present_value(finding.details)),
        )
        for finding in report.agent_findings
    ]
    insights = [
        replace(
            insight,
            skill=present_text(insight.skill),
            conclusion=present_text(insight.conclusion),
            strategy=present_text(insight.strategy),
            evidence=list(present_value(insight.evidence)),
            risks=list(present_value(insight.risks)),
            details=dict(present_value(insight.details)),
        )
        for insight in report.skill_insights
    ]
    for insight in insights:
        if insight.category == "committee":
            _inject_judge_role([{"category": insight.category, "details": insight.details}])
    return replace(
        report,
        action_plan=present_text(report.action_plan),
        bull_case=list(present_value(report.bull_case)),
        bear_case=list(present_value(report.bear_case)),
        risk_factors=list(present_value(report.risk_factors)),
        invalid_conditions=list(present_value(report.invalid_conditions)),
        agent_findings=findings,
        skill_insights=insights,
        decision_brief=dict(present_value(report.decision_brief)),
        model_interpretation=(present_text(report.model_interpretation) if report.model_interpretation else None),
    )


def research_group_title() -> str:
    return str(_config()["research_group_title"])


def judge_title() -> str:
    return str(_config()["judge_title"])


def _inject_judge_role(insights: Any) -> None:
    if not isinstance(insights, list):
        return
    for insight in insights:
        if not isinstance(insight, dict) or insight.get("category") != "committee":
            continue
        details = insight.get("details")
        if not isinstance(details, dict):
            continue
        judge = details.get("judge")
        if isinstance(judge, dict):
            judge.setdefault("role_label", str(_config()["judge_title"]))


def _config() -> dict[str, Any]:
    return load_runtime_settings().get("reporting", "presentation")
