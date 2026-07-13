from __future__ import annotations

from app.schemas.report import MarketContext, SkillInsight, StockProfile
from app.config.runtime import load_runtime_settings
from app.knowledge.theme_resolver import resolve_themes
from app.skills.common import clamp_score


def analyze_theme_lifecycle(profile: StockProfile, context: MarketContext) -> SkillInsight:
    if context.limit_up_count is None or context.failed_breakout_rate is None or context.data_status != "verified":
        return SkillInsight(
            skill="热点生命周期分析",
            category="theme",
            stage="数据不足",
            score=load_runtime_settings().get("scoring", "data_readiness", "insufficient_score"),
            conclusion="市场涨停扩散或炸板数据不完整，不能判断题材生命周期。",
            strategy="保留主题匹配结果，但不把它解释为启动、扩散或高潮。",
            evidence=[f"政策主题：{', '.join(context.policy_themes) if context.policy_themes else '未获取'}"],
            risks=list(context.unavailable_reasons) or ["政策主题和市场题材不是同一概念，不能相互替代。"],
        )
    matches = resolve_themes(profile, context.policy_themes)
    matched = [item.theme for item in matches]
    config = load_runtime_settings().get("domain_knowledge", "theme", "lifecycle")
    score = config["base_score"] + len(matched) * config["matched_theme_weight"]
    score += config["supportive_cycle_bonus"] if context.hot_money_cycle in config["supportive_hot_money_cycles"] else 0
    score += min(config["limit_up_cap"], int(context.limit_up_count) / config["limit_up_divisor"])
    final_score = clamp_score(score)
    if not matched:
        stage = "无明显主线"
    elif final_score >= config["climax_score"] and float(context.failed_breakout_rate) > config["high_failed_breakout_rate"]:
        stage = "高潮"
    elif final_score >= config["expansion_score"]:
        stage = "扩散"
    elif final_score >= config["start_score"]:
        stage = "启动"
    else:
        stage = "萌芽"
    return SkillInsight(
        skill="热点生命周期分析",
        category="theme",
        stage=stage,
        score=final_score,
        conclusion=f"{profile.industry}与当前主题处于{stage}阶段",
        strategy="主题处于启动/扩散期才适合重点研究，高潮期重点看兑现风险。",
        evidence=[
            f"个股行业 {profile.industry}",
            f"政策/市场主题：{', '.join(context.policy_themes)}",
            f"匹配主题：{', '.join(matched) if matched else '暂无'}",
            *[f"{item.theme} 来源：{item.source}" for item in matches],
        ],
        risks=["题材判断依赖主题数据完整性，需结合新闻和资金连续性复核。"],
    )
