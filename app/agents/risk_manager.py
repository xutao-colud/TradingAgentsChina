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
            if insight.skill == "情绪周期识别" and insight.stage == "数据不足":
                risk_items.append("缺少连续情绪观察，不能以单日市场统计判断短线周期。")
    risk_items.extend(invalid_conditions)
    weak_agents = [finding.agent for finding in findings if finding.score < 45]
    if weak_agents:
        risk_items.append(f"低分 Agent：{', '.join(weak_agents)}。")
    risk_skill = next((item for item in skill_insights or [] if item.category == "risk"), None)
    data_readiness = next((item for item in skill_insights or [] if item.category == "data_quality"), None)
    if data_readiness and data_readiness.score < 70:
        risk_items.extend(f"数据就绪性审查：{item}" for item in data_readiness.risks)
        return "未知", risk_items
    risk_score = risk_skill.score if risk_skill else 60
    if invalid_conditions or risk_score < 45:
        return "高", risk_items
    if risk_score < 60 or len(weak_agents) >= 2:
        return "中", risk_items
    return "低", risk_items
