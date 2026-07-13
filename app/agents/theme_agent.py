from __future__ import annotations

from app.agents.common import clamp_score, confidence_from_score
from app.knowledge.theme_resolver import resolve_themes
from app.config.runtime import load_runtime_settings
from app.schemas.report import AgentFinding, MarketContext, StockProfile


def analyze_theme(profile: StockProfile, context: MarketContext) -> AgentFinding:
    matches = resolve_themes(profile, context.policy_themes)
    matched = [item.theme for item in matches]
    config = load_runtime_settings().get("scoring", "theme")
    score = config["base"] + len(matched) * config["match_weight"]
    final_score = clamp_score(score)
    source_ids = ["profile-001", "market-001"]
    if profile.concept_source_id:
        source_ids.append(profile.concept_source_id)
    return AgentFinding(
        agent="题材热点 Agent",
        conclusion="政策与题材匹配度较高" if final_score >= config["strong_threshold"] else "题材匹配度一般",
        score=final_score,
        confidence=confidence_from_score(final_score),
        evidence=[
            f"行业：{profile.industry}",
            f"市场主题：{', '.join(context.policy_themes)}",
            f"匹配主题：{', '.join(matched) if matched else '暂无明显匹配'}",
            *[f"{item.theme} 匹配来源：{item.source}（{item.matched_value}）" for item in matches],
        ],
        risks=["题材热度有生命周期，高潮期后波动会放大。"] if matched else ["题材未形成明确匹配，不能以政策关键词替代公司受益证据。"],
        counterpoints=["题材只提高关注度，不能替代业绩验证。"],
        invalidation_conditions=["政策主题未落到公司业务、订单或产业链证据。", "题材进入退潮且核心标的、资金承接同步走弱。"],
        source_ids=source_ids,
    )
