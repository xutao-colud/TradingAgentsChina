from __future__ import annotations

from app.schemas.report import MarketContext, SkillInsight
from app.skills.sentiment_dynamics import analyze_sentiment_dynamics


def identify_sentiment_cycle(context: MarketContext) -> SkillInsight:
    dynamics = analyze_sentiment_dynamics(context)
    final_score = dynamics.score
    stage = dynamics.stage
    if stage == "数据不足":
        return SkillInsight(
            skill="情绪周期识别",
            category="market",
            stage=stage,
            score=final_score,
            conclusion="连续情绪观察不足，不能判断启动、发酵或退潮。",
            strategy="补齐连续交易日的涨跌停、炸板、连板和昨日涨停反馈后重算。",
            evidence=[f"历史观察点 {dynamics.observations}", f"市场数据状态：{context.data_status}"],
            risks=[dynamics.insufficient_reason] if dynamics.insufficient_reason else list(context.unavailable_reasons),
            details={"mode": "sentiment_dynamics", "velocity": None, "acceleration": None, "observations": dynamics.observations},
        )
    strategy = {
        "数据不足": "先补齐连续情绪观察值，不把单日涨停/炸板统计解释为周期转换。",
        "冰点": "等待情绪修复信号，减少试错。",
        "启动": "关注最先修复的核心方向，不扩散到杂毛。",
        "发酵": "跟踪主线持续性，避免后排轮动过快。",
        "高潮": "警惕一致性过高，优先做风险收益比评估。",
        "退潮": "降低短线风险暴露，不追高接力。",
        "分歧": "市场未形成方向性扩散，等待速度和承接进一步确认。",
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
            f"封板率 {context.sealed_limit_up_rate:.1f}%",
            f"一字板数量 {context.one_price_limit_up_count}",
            f"连板梯队 {context.board_ladder}",
            f"昨日涨停溢价 {context.yesterday_limit_up_premium:.2f}%",
            f"跌停数量 {context.limit_down_count}",
            f"历史观察点 {dynamics.observations}，情绪速度 {dynamics.velocity if dynamics.velocity is not None else '数据不足'}，加速度 {dynamics.acceleration if dynamics.acceleration is not None else '数据不足'}。",
        ],
        risks=["情绪周期变化快，盘中分歧会改变阶段判断。"] + ([dynamics.insufficient_reason] if dynamics.insufficient_reason else []),
        details={"mode": "sentiment_dynamics", "velocity": dynamics.velocity, "acceleration": dynamics.acceleration, "observations": dynamics.observations},
    )
