from __future__ import annotations

from app.config.runtime import load_runtime_settings
from app.schemas.report import MarketContext, SkillInsight
from app.skills.common import clamp_score, stage_by_score


def assess_money_making_effect(context: MarketContext) -> SkillInsight:
    config = load_runtime_settings().get("scoring", "money_making_effect")
    required = {
        "first_board_count": context.first_board_count,
        "second_board_success_rate": context.second_board_success_rate,
        "strong_stock_return": context.strong_stock_return,
        "failed_breakout_rate": context.failed_breakout_rate,
    }
    missing = [name for name, value in required.items() if value is None]
    if context.data_status != "verified" or context.failed_breakout_rate is None:
        return SkillInsight(
            skill="赚钱效应分析",
            category="market",
            stage="数据不足",
            score=load_runtime_settings().get("scoring", "data_readiness", "insufficient_score"),
            conclusion="赚钱效应缺少可核验的炸板反馈，不能形成短线环境判断。",
            strategy="补齐同一交易日的真实涨停与炸板数据后重算。",
            evidence=[f"缺失字段：{', '.join(missing) if missing else '无'}"],
            risks=list(context.unavailable_reasons) or ["缺失字段未按零值计算。"],
            details={"coverage_status": "insufficient", "missing_fields": missing, "as_of": context.as_of},
        )

    score = float(config["base_score"])
    if context.first_board_count is not None:
        score += min(
            float(config["first_board_cap"]),
            int(context.first_board_count) * float(config["first_board_weight"]),
        )
    if context.second_board_success_rate is not None:
        score += min(
            float(config["second_board_cap"]),
            float(context.second_board_success_rate) * float(config["second_board_weight"]),
        )
    if context.strong_stock_return is not None:
        score += min(
            float(config["strong_return_cap"]),
            float(context.strong_stock_return) * float(config["strong_return_weight"]),
        )
    score -= min(
        float(config["failed_breakout_cap"]),
        float(context.failed_breakout_rate) * float(config["failed_breakout_weight"]),
    )
    final_score = clamp_score(score)
    base_stage = stage_by_score(final_score, "较差", "一般", "良好", "强势")
    stage = f"{base_stage}（部分核验）" if missing else base_stage
    return SkillInsight(
        skill="赚钱效应分析",
        category="market",
        stage=stage,
        score=final_score,
        conclusion=(
            f"当前已核验的短线反馈为{stage}；"
            + ("缺失指标未按零值计分，不能据此形成完整接力结论。" if missing else "")
        ),
        strategy=(
            "把已核验的炸板与封板反馈作为约束条件，补齐首板、二板和强势股次日反馈后再评估接力环境。"
            if missing
            else "赚钱效应好时关注主线核心，转弱时减少追涨和接力。"
        ),
        evidence=[
            f"首板数量 {context.first_board_count}" if context.first_board_count is not None else "首板数量待核验",
            f"二板成功率 {context.second_board_success_rate:.1f}%" if context.second_board_success_rate is not None else "二板成功率待核验",
            f"强势股平均表现 {context.strong_stock_return:.2f}%" if context.strong_stock_return is not None else "强势股平均表现待核验",
            f"炸板率 {context.failed_breakout_rate:.1f}%",
            f"封板率 {context.sealed_limit_up_rate:.1f}%" if context.sealed_limit_up_rate is not None else "封板率数据不足",
            f"一字板 {context.one_price_limit_up_count} 家" if context.one_price_limit_up_count is not None else "一字板数据不足",
            f"连板梯队 {context.board_ladder}" if context.board_ladder else "连板梯队数据不足",
        ],
        risks=["赚钱效应偏强时也可能伴随高波动和隔日兑现压力。"]
        + ([f"未核验维度：{', '.join(missing)}。"] if missing else []),
        details={
            "coverage_status": "partial" if missing else "complete",
            "missing_fields": missing,
            "source_ids": ["market-001"],
            "as_of": context.as_of,
        },
    )
