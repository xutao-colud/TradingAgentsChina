from __future__ import annotations

from app.config.runtime import load_runtime_settings
from app.schemas.report import AgentFinding


def build_bear_case(findings: list[AgentFinding]) -> list[str]:
    config = load_runtime_settings().get("scoring", "research_cases")
    risks: list[str] = []
    for finding in findings:
        risks.extend(f"{finding.agent}：{risk}" for risk in finding.risks)
        if finding.score < config["bear_threshold"]:
            risks.append(f"{finding.agent}：{finding.conclusion}")
    return risks[:config["bear_limit"]]
