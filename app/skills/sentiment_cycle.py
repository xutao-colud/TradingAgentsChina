from __future__ import annotations

from app.schemas.report import MarketContext, SkillInsight
from app.skills.common import clamp_score


def identify_sentiment_cycle(context: MarketContext) -> SkillInsight:
    score = 45
    score += min(18, context.limit_up_count / 4)
    score += min(14, context.max_consecutive_boards * 2)
    score += min(12, context.yesterday_limit_up_premium * 4)
    score -= min(20, context.failed_breakout_rate * 0.7)
    score -= min(16, context.limit_down_count * 1.8)
    final_score = clamp_score(score)
    if context.failed_breakout_rate >= 35 or context.limit_down_count >= 25:
        stage = "退潮"
    elif final_score >= 82 and context.max_consecutive_boards >= 7:
        stage = "高潮"
    elif final_score >= 68:
        stage = "发酵"
    elif final_score >= 50:
        stage = "启动"
    else:
        stage = "冰点"
    strategy = {
        "冰点": "等待情绪修复信号，减少试错。",
        "启动": "关注最先修复的核心方向，不扩散到杂毛。",
        "发酵": "跟踪主线持续性，避免后排轮动过快。",
        "高潮": "警惕一致性过高，优先做风险收益比评估。",
        "退潮": "降低短线风险暴露，不追高接力。",
    }[stage]
    return SkillInsight(
        skill="情绪周期识别",
        category="market",
        stage=stage,
        score=final_score,
        conclusion=f"短线情绪处于{stage}阶段",
        strategy=strategy,
        evidence=[
            f"涨停数量 {context.limit_up_count}",
            f"连板高度 {context.max_consecutive_boards}",
            f"炸板率 {context.failed_breakout_rate:.1f}%",
            f"昨日涨停溢价 {context.yesterday_limit_up_premium:.2f}%",
            f"跌停数量 {context.limit_down_count}",
        ],
        risks=["情绪周期变化快，盘中分歧会改变阶段判断。"],
    )

