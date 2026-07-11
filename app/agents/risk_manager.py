from __future__ import annotations

from app.schemas.report import AgentFinding, SkillInsight


def assess_risk(
    findings: list[AgentFinding],
    invalid_conditions: list[str],
    skill_insights: list[SkillInsight] | None = None,
) -> tuple[str, list[str]]:
    risk_items: list[str] = []
    for finding in findings:
        risk_items.extend(finding.risks)
    if skill_insights:
        for insight in skill_insights:
            if insight.category == "risk" or insight.score < 50:
                risk_items.extend(f"{insight.skill}：{risk}" for risk in insight.risks)
            if insight.skill == "情绪周期识别" and insight.stage in {"退潮", "冰点"}:
                risk_items.append(f"短线情绪处于{insight.stage}阶段。")
    risk_items.extend(invalid_conditions)
    weak_agents = [finding.agent for finding in findings if finding.score < 45]
    if weak_agents:
        risk_items.append(f"低分 Agent：{', '.join(weak_agents)}。")
    if invalid_conditions or len(risk_items) >= 5:
        return "高", risk_items
    if len(risk_items) >= 2:
        return "中", risk_items
    return "低", risk_items
