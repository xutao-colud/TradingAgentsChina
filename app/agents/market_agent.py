from __future__ import annotations

from app.agents.common import clamp_score, confidence_from_score
from app.schemas.report import AgentFinding, MarketContext


def analyze_market(context: MarketContext) -> AgentFinding:
    breadth = context.advancers / max(1, context.advancers + context.decliners)
    score = 50 + context.index_change_pct * 12 + (breadth - 0.5) * 60
    score += min(12, context.limit_up_count / 8)
    score -= min(12, context.limit_down_count / 3)
    final_score = clamp_score(score)
    conclusion = "市场情绪弱修复" if final_score >= 60 else "市场环境偏谨慎"
    if final_score >= 72:
        conclusion = "市场环境偏积极"
    elif final_score <= 42:
        conclusion = "市场情绪偏弱"
    return AgentFinding(
        agent="市场周期 Agent",
        conclusion=conclusion,
        score=final_score,
        confidence=confidence_from_score(final_score),
        evidence=[
            f"{context.index_name}涨跌幅 {context.index_change_pct:.2f}%",
            f"上涨/下跌家数 {context.advancers}/{context.decliners}",
            f"涨停 {context.limit_up_count} 家，跌停 {context.limit_down_count} 家",
            f"游资情绪周期：{context.hot_money_cycle}",
        ],
        risks=["若成交额继续萎缩，修复可能转为弱反弹。"] if context.total_amount < 800_000_000_000 else [],
        counterpoints=["单日市场情绪不能代表中期趋势。"],
        source_ids=["market-001"],
    )

