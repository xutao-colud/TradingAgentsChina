from __future__ import annotations

from app.config.runtime import load_runtime_settings
from app.schemas.report import MarketContext, SkillInsight
from app.skills.common import clamp_score, stage_by_score


def assess_money_making_effect(context: MarketContext) -> SkillInsight:
    required = {
        "first_board_count": context.first_board_count,
        "second_board_success_rate": context.second_board_success_rate,
        "strong_stock_return": context.strong_stock_return,
        "failed_breakout_rate": context.failed_breakout_rate,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing or context.data_status != "verified":
        return SkillInsight(
            skill="赚钱效应分析",
            category="market",
            stage="数据不足",
            score=load_runtime_settings().get("scoring", "data_readiness", "insufficient_score"),
            conclusion="赚钱效应所需的涨停梯队或炸板数据不完整。",
            strategy="不生成接力或低吸战法结论，补齐涨跌停历史后重算。",
            evidence=[f"缺失字段：{', '.join(missing) if missing else '无'}"],
            risks=list(context.unavailable_reasons) or ["缺失字段未按零值计算。"],
        )
    score = 40
    score += min(20, int(context.first_board_count) * 0.35)
    score += min(20, float(context.second_board_success_rate) * 0.35)
    score += min(18, float(context.strong_stock_return) * 4)
    score -= min(18, float(context.failed_breakout_rate) * 0.45)
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
            f"封板率 {context.sealed_limit_up_rate:.1f}%" if context.sealed_limit_up_rate is not None else "封板率数据不足",
            f"一字板 {context.one_price_limit_up_count} 家" if context.one_price_limit_up_count is not None else "一字板数据不足",
            f"连板梯队 {context.board_ladder}" if context.board_ladder else "连板梯队数据不足",
        ],
        risks=["赚钱效应偏强时也可能伴随高波动和隔日兑现压力。"],
    )
