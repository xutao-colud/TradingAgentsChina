from __future__ import annotations

from app.config.runtime import load_runtime_settings
from app.schemas.report import AgentFinding


def build_bull_case(findings: list[AgentFinding]) -> list[str]:
    config = load_runtime_settings().get("scoring", "research_cases")
    selected = [finding for finding in findings if finding.score >= config["bull_threshold"]]
    return [f"{finding.agent}：{finding.conclusion}" for finding in selected[:config["bull_limit"]]]
