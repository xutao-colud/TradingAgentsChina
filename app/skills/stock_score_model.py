from __future__ import annotations

from app.schemas.report import AgentFinding, SkillInsight
from app.skills.common import clamp_score


def score_stock_composite(findings: list[AgentFinding], skill_insights: list[SkillInsight]) -> SkillInsight:
    data_readiness = next((item for item in skill_insights if item.category == "data_quality"), None)
    if data_readiness and data_readiness.score < 70:
        return SkillInsight(
            skill="股票综合评分模型",
            category="decision",
            stage="不可用",
            score=0,
            conclusion="数据就绪性不足，综合评分不参与排序。",
            strategy="补齐生产来源和足够日线历史后，再计算跨维度信号分数。",
            evidence=[f"数据状态：{data_readiness.stage}"],
            risks=list(data_readiness.risks),
        )
    agent_score = sum(item.score for item in findings) / max(1, len(findings))
    signal_skills = [
        item
        for item in skill_insights
        if item.category in {"market", "theme", "capital", "news"}
        and item.details.get("admitted") is not False
    ]
    skill_score = sum(item.score for item in signal_skills) / max(1, len(signal_skills))
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
            f"信号类 Skills 均分 {skill_score:.1f}（不含数据质量、个性化、路线选择和委员会）",
            f"风险惩罚 {risk_penalty}",
        ],
        risks=["综合评分会掩盖单项重大风险，因此不能越过风控规则。"],
    )
