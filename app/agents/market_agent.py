from __future__ import annotations

from app.agents.common import clamp_score, confidence_from_score
from app.config.runtime import load_runtime_settings
from app.indicators.market_breadth import evaluate_market_breadth_confirmation
from app.schemas.report import AgentFinding, MarketContext


def analyze_market(context: MarketContext) -> AgentFinding:
    required = {
        "index_change_pct": context.index_change_pct,
        "total_amount": context.total_amount,
        "advancers": context.advancers,
        "decliners": context.decliners,
        "limit_up_count": context.limit_up_count,
        "limit_down_count": context.limit_down_count,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing or context.data_status != "verified":
        return AgentFinding(
            agent="市场周期 Agent",
            conclusion="市场状态数据不足，不能选择战法",
            score=load_runtime_settings().get("scoring", "data_readiness", "insufficient_score"),
            confidence=0.0,
            evidence=[f"缺失字段：{', '.join(missing) if missing else '无'}", f"市场数据状态：{context.data_status}"],
            risks=list(context.unavailable_reasons) or ["不得把缺失市场数据解释为零值或情绪冰点。"],
            counterpoints=["单一指数数据不能替代全市场宽度和涨跌停统计。"],
            invalidation_conditions=["补齐同一交易日的市场宽度、涨跌停池及连续情绪历史后重新判断。"],
            source_ids=[],
        )

    advancers = int(context.advancers)
    decliners = int(context.decliners)
    breadth = advancers / max(1, advancers + decliners)
    config = load_runtime_settings().get("scoring", "market")
    breadth_confirmation = evaluate_market_breadth_confirmation(context)
    neutral = load_runtime_settings().get("scoring", "score_bounds", "neutral")
    score = neutral + float(context.index_change_pct) * config["index_weight"] + (breadth - 0.5) * config["breadth_weight"]
    score += min(config["limit_up_cap"], int(context.limit_up_count) / config["limit_up_divisor"])
    score -= min(config["limit_down_cap"], int(context.limit_down_count) / config["limit_down_divisor"])
    score += breadth_confirmation.score_adjustment
    final_score = clamp_score(score)
    conclusion = "市场情绪弱修复" if final_score >= config["repair_threshold"] else "市场环境偏谨慎"
    if final_score >= config["positive_threshold"]:
        conclusion = "市场环境偏积极"
    elif final_score <= config["weak_threshold"]:
        conclusion = "市场情绪偏弱"
    return AgentFinding(
        agent="市场周期 Agent",
        conclusion=conclusion,
        score=final_score,
        confidence=min(confidence_from_score(final_score), breadth_confirmation.confidence_cap),
        evidence=[
            f"{context.index_name}涨跌幅 {float(context.index_change_pct):.2f}%",
            f"上涨/下跌家数 {context.advancers}/{context.decliners}",
            f"涨停 {context.limit_up_count} 家，跌停 {context.limit_down_count} 家",
            f"封板率 {context.sealed_limit_up_rate:.1f}%，一字板 {context.one_price_limit_up_count} 家，连板梯队 {context.board_ladder}" if context.sealed_limit_up_rate is not None else "涨停结构数据不足",
            f"动态游资情绪周期：{context.hot_money_cycle}",
            f"数据时间：{context.as_of}",
            f"市场广度交叉核验：{breadth_confirmation.stage}",
            *breadth_confirmation.evidence,
        ],
        risks=(
            ["若成交额继续萎缩，修复可能转为弱反弹。"]
            if float(context.total_amount) < config["low_amount"]
            else ["市场状态仅描述同一时点，盘中成交和涨跌停结构变化可能使交叉确认失效。"]
        ) + breadth_confirmation.risks + list(context.unavailable_reasons),
        counterpoints=["单日市场状态不能代表中期趋势。", *breadth_confirmation.counterpoints],
        invalidation_conditions=["上涨家数转弱且跌停数量连续增加。", "成交额持续低于近期均值，风险偏好未获确认。"],
        source_ids=["market-001"],
    )
