from __future__ import annotations

from app.schemas.report import AgentFinding


def build_bull_case(findings: list[AgentFinding]) -> list[str]:
    selected = [finding for finding in findings if finding.score >= 60]
    return [f"{finding.agent}：{finding.conclusion}" for finding in selected[:5]]

