from __future__ import annotations

from app.schemas.report import MarketContext, SkillInsight
from app.skills.common import clamp_score, stage_by_score


def assess_money_making_effect(context: MarketContext) -> SkillInsight:
    score = 40
    score += min(20, context.first_board_count * 0.35)
    score += min(20, context.second_board_success_rate * 0.35)
    score += min(18, context.strong_stock_return * 4)
    score -= min(18, context.failed_breakout_rate * 0.45)
    final_score = clamp_score(score)
    stage = stage_by_score(final_score, "较差", "一般", "良好", "强势")
    return SkillInsight(
        skill="赚钱效应分析",
        category="market",
        stage=stage,
        score=final_score,
        conclusion=f"短线赚钱效应{stage}",
        strategy="赚钱效应好时关注主线核心，转弱时减少追涨和接力。",
        evidence=[
            f"首板数量 {context.first_board_count}",
            f"二板成功率 {context.second_board_success_rate:.1f}%",
            f"强势股平均表现 {context.strong_stock_return:.2f}%",
            f"炸板率 {context.failed_breakout_rate:.1f}%",
        ],
        risks=["赚钱效应偏强时也可能伴随高波动和隔日兑现压力。"],
    )

