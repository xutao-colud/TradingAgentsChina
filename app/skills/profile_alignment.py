from __future__ import annotations

from app.config.runtime import load_runtime_settings
from app.memory.models import TradingProfile
from app.schemas.report import AgentFinding, SkillInsight
from app.skills.common import clamp_score


def assess_profile_alignment(
    profile: TradingProfile | None,
    findings: list[AgentFinding],
    skill_insights: list[SkillInsight],
) -> SkillInsight | None:
    """Turn explicit user preferences into a transparent report constraint.

    This deliberately does not infer a new preference from market data.  It only
    uses a saved profile and current deterministic signals to say whether the
    setup is compatible with that profile.
    """
    if profile is None:
        return None
    config = load_runtime_settings().get("scoring", "profile_alignment")

    data_readiness = next((item for item in skill_insights if item.category == "data_quality"), None)
    if data_readiness and data_readiness.score < config["readiness_threshold"]:
        return SkillInsight(
            skill="个人交易画像适配",
            category="personalization",
            stage="待数据确认",
            score=0,
            conclusion="数据就绪性不足，不能判断当前机会是否适合该用户的交易画像。",
            strategy="保留用户偏好，但先补齐真实、同日期的市场和个股数据。",
            evidence=[f"交易风格：{profile.style}", f"数据状态：{data_readiness.stage}"],
            risks=list(data_readiness.risks),
        )

    technical = next((item for item in findings if item.agent == "技术分析 Agent"), None)
    sentiment = next((item for item in skill_insights if item.skill == "情绪周期识别"), None)
    risk = next((item for item in skill_insights if item.skill == "A股风险扫描器"), None)

    score = config["base_score"]
    evidence = [
        f"交易风格：{profile.style}",
        f"持有周期：{profile.holding_period}",
        f"偏好形态：{'、'.join(profile.preferred_setups) or '未设置'}",
        f"回避形态：{'、'.join(profile.avoid_patterns) or '未设置'}",
    ]
    risks: list[str] = []
    if technical and technical.score >= config["technical_threshold"]:
        score += config["technical_bonus"]
        evidence.append(f"技术面得分 {technical.score}，趋势条件基本满足。")
    elif technical:
        score -= config["technical_penalty"]
        risks.append("技术趋势未达到个人策略的确认阈值。")

    if sentiment and sentiment.stage in set(config["sentiment_risk_stages"]):
        score -= config["sentiment_penalty"]
        risks.append(f"当前情绪处于{sentiment.stage}，与稳健跟随/低吸打法不完全匹配。")
    elif sentiment:
        score += config["sentiment_bonus"]
        evidence.append(f"情绪周期：{sentiment.stage}。")

    if risk and risk.score < config["risk_threshold"]:
        score -= config["risk_penalty"]
        risks.append("风险扫描未达到个人策略的基础门槛。")

    score = clamp_score(score)
    if score >= config["fit_threshold"]:
        stage = "适配"
        conclusion = "当前研究结论与已保存的交易画像基本适配"
        strategy = "仍按个人仓位和风险规则执行；不因适配度高而追涨。"
    elif score >= config["watch_threshold"]:
        stage = "等待确认"
        conclusion = "当前机会部分符合交易画像，需等待更明确的入场条件"
        strategy = "优先等待趋势、量能或公告信号确认，再决定是否纳入观察。"
    else:
        stage = "不适配"
        conclusion = "当前机会与已保存的交易画像不适配"
        strategy = "保留研究记录，不将其转化为符合个人打法的行动计划。"

    return SkillInsight(
        skill="个人交易画像适配",
        category="personalization",
        stage=stage,
        score=score,
        conclusion=conclusion,
        strategy=strategy,
        evidence=evidence,
        risks=risks,
    )
