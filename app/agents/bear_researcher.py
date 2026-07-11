from __future__ import annotations

from app.schemas.report import AgentFinding


def build_bear_case(findings: list[AgentFinding]) -> list[str]:
    risks: list[str] = []
    for finding in findings:
        risks.extend(f"{finding.agent}：{risk}" for risk in finding.risks)
        if finding.score < 50:
            risks.append(f"{finding.agent}：{finding.conclusion}")
    return risks[:6]

