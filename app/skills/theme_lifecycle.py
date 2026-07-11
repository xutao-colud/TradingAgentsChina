from __future__ import annotations

from app.schemas.report import MarketContext, SkillInsight, StockProfile
from app.skills.common import clamp_score


def analyze_theme_lifecycle(profile: StockProfile, context: MarketContext) -> SkillInsight:
    matched = _matched_themes(profile, context.policy_themes)
    score = 48 + len(matched) * 12
    score += 6 if context.hot_money_cycle in {"弱修复", "发酵", "震荡修复"} else 0
    score += min(10, context.limit_up_count / 10)
    final_score = clamp_score(score)
    if not matched:
        stage = "无明显主线"
    elif final_score >= 82 and context.failed_breakout_rate > 25:
        stage = "高潮"
    elif final_score >= 75:
        stage = "扩散"
    elif final_score >= 60:
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
        ],
        risks=["题材判断依赖主题数据完整性，需结合新闻和资金连续性复核。"],
    )


def _matched_themes(profile: StockProfile, themes: list[str]) -> list[str]:
    industry_map = {
        "白酒": {"消费复苏", "高股息"},
        "食品饮料": {"消费复苏", "高股息"},
        "半导体": {"半导体国产替代", "AI算力"},
        "机器人": {"机器人", "高端制造"},
        "电池": {"新能源", "储能"},
    }
    candidates = industry_map.get(profile.industry, set())
    return [theme for theme in themes if theme in candidates or theme == "国企改革"]

