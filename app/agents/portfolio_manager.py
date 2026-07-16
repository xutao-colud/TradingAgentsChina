from __future__ import annotations

from app.agents.common import average_score
from app.config.runtime import load_runtime_settings
from app.schemas.report import AgentFinding, SkillInsight


def decide_rating(
    findings: list[AgentFinding],
    invalid_conditions: list[str],
    skill_insights: list[SkillInsight] | None = None,
) -> tuple[str, str, float]:
    config = load_runtime_settings().get("scoring", "portfolio_manager")
    weighted = average_score([finding.score for finding in findings])
    confidence = round(sum(finding.confidence for finding in findings) / max(1, len(findings)), 2)
    data_readiness = None
    if skill_insights:
        data_readiness = next((item for item in skill_insights if item.category == "data_quality"), None)
        composite = next((item for item in skill_insights if item.skill == "股票综合评分模型"), None)
        if composite:
            weighted = int(round(weighted * config["finding_weight"] + composite.score * config["composite_weight"]))
        risk_skill = next((item for item in skill_insights if item.skill == "A股风险扫描器"), None)
        cycle_skill = next((item for item in skill_insights if item.skill == "情绪周期识别"), None)
        if risk_skill and risk_skill.score < config["risk_threshold"]:
            weighted = min(weighted, config["risk_score_cap"])
        if cycle_skill and cycle_skill.stage in {"退潮", "冰点"}:
            weighted = min(weighted, config["retreat_score_cap"])
        if cycle_skill and cycle_skill.stage == "数据不足":
            weighted = min(weighted, config["sentiment_missing_cap"])
        profile_skill = next((item for item in skill_insights if item.category == "personalization"), None)
        if profile_skill and profile_skill.stage == "不适配":
            weighted = min(weighted, config["profile_mismatch_cap"])
        playbook_skill = next((item for item in skill_insights if item.category == "playbook"), None)
        if playbook_skill and playbook_skill.stage in {"不适配", "市场不适配"}:
            weighted = min(weighted, config["playbook_mismatch_cap"])
        committee_skill = next((item for item in skill_insights if item.skill == "投资流派委员会"), None)
        if committee_skill and committee_skill.stage.startswith("防守风控派"):
            weighted = min(weighted, config["defensive_committee_cap"])
        evidence_skill = next((item for item in skill_insights if item.skill == "证据链完整性"), None)
        if evidence_skill and evidence_skill.score < config["evidence_usable_threshold"]:
            weighted = min(weighted, config["evidence_usable_cap"])
        if evidence_skill and evidence_skill.score < config["evidence_weak_threshold"]:
            weighted = min(weighted, config["evidence_weak_cap"])
        if data_readiness and data_readiness.score < config["readiness_threshold"]:
            weighted = min(weighted, config["readiness_cap"])
        weak_skills = sum(1 for item in skill_insights if item.score < config["weak_skill_threshold"])
        confidence = round(max(config["confidence_floor"], confidence - weak_skills * config["weak_skill_confidence_penalty"]), 2)
    if invalid_conditions:
        weighted = min(weighted, config["invalid_condition_cap"])
    if data_readiness and data_readiness.score < config["readiness_threshold"]:
        confidence = round(min(confidence, data_readiness.score / 100), 2)
        return "证据不足", "关键来源不完整、时点不匹配或仍含样例数据；仅保存研究草稿，补齐数据后再评估。", confidence
    if config["sentiment_missing_is_hard_block"] and skill_insights and any(item.skill == "情绪周期识别" and item.stage == "数据不足" for item in skill_insights):
        return "证据不足", "缺少连续市场情绪观察，无法选择与情绪周期相关的战法；补齐历史观察后再评估。", min(confidence, config["sentiment_missing_confidence_cap"])
    if weighted >= config["strong_threshold"]:
        conclusion = "强烈关注"
        action_plan = "只在市场情绪延续、回踩关键均线不破时继续跟踪，不追涨。"
    elif weighted >= config["positive_threshold"]:
        conclusion = "谨慎关注"
        action_plan = "等待缩量回踩或公告确认后分批观察，跌破20日线降低关注。"
    elif weighted >= config["neutral_threshold"]:
        conclusion = "中性观察"
        action_plan = "保持观察，等待资金连续性和市场情绪进一步确认。"
    elif weighted >= config["risk_threshold_score"]:
        conclusion = "风险较高"
        action_plan = "避免追高，优先等待风险释放。"
    else:
        conclusion = "暂不参与"
        action_plan = "规则或风险条件未满足，不形成参与计划。"
    return conclusion, action_plan, confidence
