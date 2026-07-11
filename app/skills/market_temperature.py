from __future__ import annotations

from app.schemas.report import MarketContext, SkillInsight
from app.skills.common import clamp_score, stage_by_score


def assess_market_temperature(context: MarketContext) -> SkillInsight:
    breadth = context.advancers / max(1, context.advancers + context.decliners)
    amount_score = min(18, context.total_amount / 100_000_000_000)
    limit_score = min(16, context.limit_up_count / 5) - min(12, context.limit_down_count / 2)
    score = 42 + context.index_change_pct * 9 + (breadth - 0.5) * 70 + amount_score + limit_score
    final_score = clamp_score(score)
    stage = stage_by_score(final_score, "防守", "震荡", "震荡修复", "进攻")
    strategy = {
        "进攻": "可提高观察密度，但仍避免情绪高潮后的追高。",
        "震荡修复": "轻仓试错，优先选择有业绩和资金共振的方向。",
        "震荡": "等待主线确认，控制频率。",
        "防守": "以风险排查和现金仓位为主。",
    }[stage]
    return SkillInsight(
        skill="A股市场温度计",
        category="market",
        stage=stage,
        score=final_score,
        conclusion=f"市场温度处于{stage}区间",
        strategy=strategy,
        evidence=[
            f"成交额 {context.total_amount / 100_000_000:.0f} 亿元",
            f"上涨比例 {breadth * 100:.1f}%",
            f"涨停/跌停 {context.limit_up_count}/{context.limit_down_count}",
            f"{context.index_name}涨跌幅 {context.index_change_pct:.2f}%",
        ],
        risks=["温度计反映市场整体环境，不能替代个股风险审查。"],
    )

