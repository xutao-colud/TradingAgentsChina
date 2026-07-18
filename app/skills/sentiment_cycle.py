from __future__ import annotations

from app.config.runtime import load_runtime_settings
from app.schemas.report import MarketContext, SkillInsight
from app.skills.common import clamp_score
from app.skills.sentiment_dynamics import analyze_sentiment_dynamics


def identify_sentiment_cycle(context: MarketContext) -> SkillInsight:
    dynamics = analyze_sentiment_dynamics(context)
    if dynamics.stage == "数据不足":
        required = (context.limit_up_count, context.limit_down_count, context.failed_breakout_rate, context.sealed_limit_up_rate)
        if context.data_status == "verified" and all(value is not None for value in required):
            config = load_runtime_settings().get("domain_knowledge", "sentiment")
            score = float(config["base_score"])
            score += int(context.limit_up_count) / float(config["limit_up_scale"])
            score -= int(context.limit_down_count) / float(config["limit_down_scale"])
            score -= float(context.failed_breakout_rate) * float(config["breakout_scale"])
            score += (float(context.sealed_limit_up_rate) - float(config["seal_rate_neutral_pct"])) * float(config["seal_rate_weight"])
            if context.one_price_limit_up_count is not None:
                score += min(float(config["one_price_count_cap"]), int(context.one_price_limit_up_count) * float(config["one_price_count_weight"]))
            return SkillInsight(
                skill="情绪周期识别",
                category="market",
                stage="单日反馈（周期待积累）",
                score=clamp_score(score),
                conclusion="已取得当日涨跌停、封板和炸板反馈，但没有连续交易日序列；只能描述当日情绪，不能判定启动、发酵或退潮。",
                strategy="市场策略门禁仍按情绪历史不足处理；持续保存同口径交易日快照，达到门槛后再识别周期。",
                evidence=[
                    f"涨停/跌停 {context.limit_up_count}/{context.limit_down_count}",
                    f"封板率/炸板率 {context.sealed_limit_up_rate:.1f}%/{context.failed_breakout_rate:.1f}%",
                    f"一字板 {context.one_price_limit_up_count} 家" if context.one_price_limit_up_count is not None else "一字板待核验",
                    f"连续情绪观察 {dynamics.observations} 个",
                ],
                risks=[dynamics.insufficient_reason or "缺少连续市场情绪观察值。", *context.unavailable_reasons],
                details={
                    "mode": "sentiment_dynamics",
                    "coverage_status": "partial",
                    "velocity": None,
                    "acceleration": None,
                    "observations": dynamics.observations,
                },
            )
        return SkillInsight(
            skill="情绪周期识别",
            category="market",
            stage="数据不足",
            score=dynamics.score,
            conclusion="当日情绪核心反馈与连续历史均不足，不能判断情绪周期。",
            strategy="补齐同一口径的涨跌停、炸板与连续情绪观察后重算。",
            evidence=[f"历史观察点 {dynamics.observations}", f"市场数据状态：{context.data_status}"],
            risks=[dynamics.insufficient_reason] if dynamics.insufficient_reason else list(context.unavailable_reasons),
            details={"mode": "sentiment_dynamics", "coverage_status": "insufficient", "observations": dynamics.observations},
        )

    strategy = {
        "冰点": "等待情绪修复信号，减少试错。",
        "启动": "关注最先修复的核心方向，不扩散到杂毛。",
        "发酵": "跟踪主线持续性，避免后排轮动过快。",
        "高潮": "警惕一致性过高，优先做风险收益比评估。",
        "退潮": "降低短线风险暴露，不追高接力。",
        "分歧": "市场未形成方向性扩散，等待速度和承接进一步确认。",
    }[dynamics.stage]
    return SkillInsight(
        skill="情绪周期识别",
        category="market",
        stage=dynamics.stage,
        score=dynamics.score,
        conclusion=f"连续同口径证据显示短线情绪处于{dynamics.stage}阶段。",
        strategy=strategy,
        evidence=[
            f"涨停数量 {context.limit_up_count}",
            f"连板高度 {context.max_consecutive_boards}",
            f"炸板率 {context.failed_breakout_rate:.1f}%",
            f"封板率 {context.sealed_limit_up_rate:.1f}%",
            f"昨日涨停溢价 {context.yesterday_limit_up_premium:.2f}%",
            f"历史观察点 {dynamics.observations}，情绪速度 {dynamics.velocity:.3f}，加速度 {dynamics.acceleration:.3f}",
        ],
        risks=["情绪周期变化快，盘中分歧会改变阶段判断。"],
        details={
            "mode": "sentiment_dynamics",
            "coverage_status": "complete",
            "velocity": dynamics.velocity,
            "acceleration": dynamics.acceleration,
            "observations": dynamics.observations,
        },
    )
