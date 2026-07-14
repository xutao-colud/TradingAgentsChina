from __future__ import annotations

from app.agents.common import average_score
from app.schemas.report import AgentFinding, SkillInsight


def decide_rating(
    findings: list[AgentFinding],
    invalid_conditions: list[str],
    skill_insights: list[SkillInsight] | None = None,
) -> tuple[str, str, float]:
    weighted = average_score([finding.score for finding in findings])
    confidence = round(sum(finding.confidence for finding in findings) / max(1, len(findings)), 2)
    data_readiness = None
    if skill_insights:
        data_readiness = next((item for item in skill_insights if item.category == "data_quality"), None)
        composite = next((item for item in skill_insights if item.skill == "股票综合评分模型"), None)
        if composite:
            weighted = int(round(weighted * 0.65 + composite.score * 0.35))
        risk_skill = next((item for item in skill_insights if item.skill == "A股风险扫描器"), None)
        cycle_skill = next((item for item in skill_insights if item.skill == "情绪周期识别"), None)
        if risk_skill and risk_skill.score < 60:
            weighted = min(weighted, 50)
        if cycle_skill and cycle_skill.stage in {"退潮", "冰点"}:
            weighted = min(weighted, 58)
        if cycle_skill and cycle_skill.stage == "数据不足":
            weighted = min(weighted, 49)
        profile_skill = next((item for item in skill_insights if item.category == "personalization"), None)
        if profile_skill and profile_skill.stage == "不适配":
            weighted = min(weighted, 58)
        playbook_skill = next((item for item in skill_insights if item.category == "playbook"), None)
        if playbook_skill and playbook_skill.stage in {"不适配", "市场不适配"}:
            weighted = min(weighted, 58)
        committee_skill = next((item for item in skill_insights if item.skill == "投资流派委员会"), None)
        if committee_skill and committee_skill.stage.startswith("防守风控派"):
            weighted = min(weighted, 56)
        evidence_skill = next((item for item in skill_insights if item.skill == "证据链完整性"), None)
        if evidence_skill and evidence_skill.score < 70:
            weighted = min(weighted, 58)
        if evidence_skill and evidence_skill.score < 55:
            weighted = min(weighted, 50)
        if data_readiness and data_readiness.score < 70:
            weighted = min(weighted, 49)
        weak_skills = sum(1 for item in skill_insights if item.score < 50)
        confidence = round(max(0.35, confidence - weak_skills * 0.04), 2)
    if invalid_conditions:
        weighted = min(weighted, 55)
    if data_readiness and data_readiness.score < 70:
        confidence = round(min(confidence, data_readiness.score / 100), 2)
        return "证据不足", "关键来源不完整、时点不匹配或仍含样例数据；仅保存研究草稿，补齐数据后再评估。", confidence
    if skill_insights and any(item.skill == "情绪周期识别" and item.stage == "数据不足" for item in skill_insights):
        return "证据不足", "缺少连续市场情绪观察，无法选择与情绪周期相关的战法；补齐历史观察后再评估。", min(confidence, 0.5)
    if weighted >= 78:
        conclusion = "强烈关注"
        action_plan = "只在市场情绪延续、回踩关键均线不破时继续跟踪，不追涨。"
    elif weighted >= 65:
        conclusion = "谨慎关注"
        action_plan = "等待缩量回踩或公告确认后分批观察，跌破20日线降低关注。"
    elif weighted >= 50:
        conclusion = "中性观察"
        action_plan = "保持观察，等待资金连续性和市场情绪进一步确认。"
    elif weighted >= 40:
        conclusion = "风险较高"
        action_plan = "避免追高，优先等待风险释放。"
    else:
        conclusion = "暂不参与"
        action_plan = "规则或风险条件未满足，不形成参与计划。"
    return conclusion, action_plan, confidence
