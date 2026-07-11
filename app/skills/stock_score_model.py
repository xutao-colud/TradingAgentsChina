from __future__ import annotations

from app.schemas.report import AgentFinding, SkillInsight
from app.skills.common import clamp_score


def score_stock_composite(findings: list[AgentFinding], skill_insights: list[SkillInsight]) -> SkillInsight:
    agent_score = sum(item.score for item in findings) / max(1, len(findings))
    skill_score = sum(item.score for item in skill_insights) / max(1, len(skill_insights))
    risk_penalty = sum(1 for item in skill_insights if item.category == "risk" and item.score < 60) * 8
    total = clamp_score(agent_score * 0.62 + skill_score * 0.38 - risk_penalty)
    if total >= 78:
        stage = "强"
    elif total >= 65:
        stage = "偏强"
    elif total >= 50:
        stage = "中性"
    else:
        stage = "偏弱"
    return SkillInsight(
        skill="股票综合评分模型",
        category="decision",
        stage=stage,
        score=total,
        conclusion=f"综合评分{stage}",
        strategy="综合分只作为投研排序信号，最终仍由风险扫描和证据质量约束。",
        evidence=[
            f"Agent均分 {agent_score:.1f}",
            f"Skills均分 {skill_score:.1f}",
            f"风险惩罚 {risk_penalty}",
        ],
        risks=["综合评分会掩盖单项重大风险，因此不能越过风控规则。"],
    )

