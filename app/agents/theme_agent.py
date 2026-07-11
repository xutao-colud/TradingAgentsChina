from __future__ import annotations

from app.agents.common import clamp_score, confidence_from_score
from app.schemas.report import AgentFinding, MarketContext, StockProfile


def analyze_theme(profile: StockProfile, context: MarketContext) -> AgentFinding:
    matched = [theme for theme in context.policy_themes if theme in {"消费复苏", "高股息", "国企改革"}]
    score = 50 + len(matched) * 8
    if profile.industry in {"白酒", "食品饮料", "消费"} and "消费复苏" in context.policy_themes:
        score += 10
    final_score = clamp_score(score)
    return AgentFinding(
        agent="题材热点 Agent",
        conclusion="政策与题材匹配度较高" if final_score >= 65 else "题材匹配度一般",
        score=final_score,
        confidence=confidence_from_score(final_score),
        evidence=[
            f"行业：{profile.industry}",
            f"市场主题：{', '.join(context.policy_themes)}",
            f"匹配主题：{', '.join(matched) if matched else '暂无明显匹配'}",
        ],
        risks=["题材热度有生命周期，高潮期后波动会放大。"] if matched else [],
        counterpoints=["题材只提高关注度，不能替代业绩验证。"],
        source_ids=["market-001"],
    )

