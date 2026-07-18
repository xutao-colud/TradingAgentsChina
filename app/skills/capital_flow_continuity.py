from __future__ import annotations

from app.config.runtime import load_runtime_settings
from app.schemas.report import CapitalFlowObservation, DailyPrice, SkillInsight
from app.skills.common import clamp_score


def analyze_capital_flow_continuity(
    prices: list[DailyPrice],
    history: list[CapitalFlowObservation],
) -> SkillInsight:
    config = load_runtime_settings().get("domain_knowledge", "capital_flow_continuity")
    ordered_history = sorted(history, key=lambda item: item.trade_date)
    source_ids = _unique([source_id for item in ordered_history for source_id in item.source_ids])
    if len({item.trade_date for item in ordered_history}) != len(ordered_history):
        return SkillInsight(
            "资金流连续性分析", "capital", "数据不足", 0,
            "历史资金数据存在重复交易日，不能可靠计算连续性。",
            "先完成交易日唯一性校验和去重，再重新计算。",
            evidence=[f"原始观察 {len(ordered_history)} 条"],
            risks=["重复日期可能放大累计净额或连续天数。"],
            details={"observations": len(ordered_history), "source_ids": source_ids},
        )
    if 0 < len(ordered_history) < config["minimum_history_points"]:
        observed_main = [item.main_net_inflow for item in ordered_history if item.main_net_inflow is not None]
        cumulative = sum(observed_main) if observed_main else None
        return SkillInsight(
            skill="资金流连续性分析",
            category="capital",
            stage="样本积累中",
            score=clamp_score(config["neutral_score"]),
            conclusion=(
                f"已取得 {len(ordered_history)} 个不同交易日的真实资金观察，但尚未达到 "
                f"{config['minimum_history_points']} 日连续性门槛。"
            ),
            strategy="仅展示已观察区间和累计方向；继续积累交易日，不把短样本外推为连续趋势。",
            evidence=[
                f"历史区间：{ordered_history[0].trade_date} 至 {ordered_history[-1].trade_date}",
                f"有效历史观察 {len(ordered_history)}/{config['minimum_history_points']} 条",
                f"已观察主力净额合计：{_format_optional(cumulative)}",
            ],
            risks=["样本尚短，只能说明已观察区间，不能生成3日/5日连续流入、流出或价资背离结论。"],
            details={
                "observations": len(ordered_history),
                "required_observations": config["minimum_history_points"],
                "coverage_status": "accumulating",
                "observed_cumulative_main_flow": cumulative,
                "source_ids": source_ids,
                "as_of": ordered_history[-1].trade_date,
            },
        )
    if len(ordered_history) < config["minimum_history_points"]:
        return SkillInsight(
            skill="资金流连续性分析",
            category="capital",
            stage="数据不足",
            score=0,
            conclusion="历史资金观察点不足，不能把单日净流入或净流出解释为连续趋势。",
            strategy="补齐连续交易日的主力资金、北向持股和融资余额后重新计算。",
            evidence=[f"有效历史观察 {len(ordered_history)} 条"],
            risks=["数据不足时不得生成连续流入、连续减仓或价资背离结论。"],
            details={
                "observations": len(ordered_history),
                "required_observations": config["minimum_history_points"],
                "source_ids": source_ids,
            },
        )

    observation_by_date = {item.trade_date: item for item in ordered_history}
    price_by_date = {item.trade_date: item.close for item in prices}
    aligned_dates = sorted(price_by_date)[-int(config["alignment_history_points"]):]
    aligned_observations = sum(trade_date in observation_by_date for trade_date in aligned_dates)
    if aligned_observations < config["minimum_history_points"]:
        return SkillInsight(
            "资金流连续性分析", "capital", "数据不足", 0,
            "资金历史与日线交易日无法形成足够的日期交集，不能计算连续性或价资背离。",
            "核对复权日线与资金数据的交易日、证券代码和分析日期后重新计算。",
            evidence=[f"日期对齐观察 {aligned_observations} 条"],
            risks=["未对齐的数据不得跨日期拼接。"],
            details={
                "observations": len(ordered_history),
                "aligned_observations": aligned_observations,
                "required_observations": config["minimum_history_points"],
                "source_ids": source_ids,
            },
        )
    main_values = [
        observation_by_date[trade_date].main_net_inflow if trade_date in observation_by_date else None
        for trade_date in aligned_dates
    ]
    northbound_values = [
        observation_by_date[trade_date].northbound_holding_change if trade_date in observation_by_date else None
        for trade_date in aligned_dates
    ]
    margin_values = [
        observation_by_date[trade_date].margin_balance if trade_date in observation_by_date else None
        for trade_date in aligned_dates
    ]
    margin_changes = [
        None if previous is None or current is None else current - previous
        for previous, current in zip(margin_values, margin_values[1:])
    ]

    main_streak = _signed_streak(main_values)
    northbound_streak = _signed_streak(northbound_values)
    margin_streak = _signed_streak(margin_changes)
    cumulative_flows: dict[str, float | None] = {}
    price_returns: dict[str, float | None] = {}
    for window in config["windows"]:
        key = f"{window}d"
        values = main_values[-window:]
        cumulative_flows[key] = sum(float(value) for value in values) if len(values) == window and all(value is not None for value in values) else None
        window_dates = aligned_dates[-window:]
        if len(window_dates) == window and price_by_date[window_dates[0]] != 0:
            price_returns[key] = (price_by_date[window_dates[-1]] / price_by_date[window_dates[0]] - 1) * 100
        else:
            price_returns[key] = None

    divergence_type: str | None = None
    divergence_window: int | None = None
    for window in sorted(config["windows"], reverse=True):
        key = f"{window}d"
        flow_value = cumulative_flows[key]
        price_return = price_returns[key]
        if flow_value is None or price_return is None:
            continue
        if price_return >= config["minimum_divergence_price_pct"] and flow_value <= -config["minimum_divergence_flow"]:
            divergence_type, divergence_window = "price_up_flow_out", window
            break
        if price_return <= -config["minimum_divergence_price_pct"] and flow_value >= config["minimum_divergence_flow"]:
            divergence_type, divergence_window = "price_down_flow_in", window
            break

    score = float(config["neutral_score"])
    score += _streak_impact(main_streak, config["main_streak_day_weight"], config["maximum_streak_impact"])
    score += _streak_impact(northbound_streak, config["northbound_streak_day_weight"], config["maximum_streak_impact"])
    score += _streak_impact(margin_streak, config["margin_streak_day_weight"], config["maximum_streak_impact"])
    if divergence_type == "price_up_flow_out":
        score -= config["divergence_penalty"]

    minimum_streak = int(config["minimum_streak_days"])
    if divergence_type == "price_up_flow_out":
        stage = "价涨资金流出背离"
        conclusion = "价格上涨但多日主力资金累计流出，当前量价资金证据存在背离。"
    elif divergence_type == "price_down_flow_in":
        stage = "价跌资金流入背离"
        conclusion = "价格下跌但多日主力资金累计流入，当前只确认背离，不推断吸筹。"
    elif main_streak >= minimum_streak:
        stage = "主力连续净流入"
        conclusion = f"主力资金已连续 {main_streak} 个有效交易日净流入。"
    elif main_streak <= -minimum_streak:
        stage = "主力连续净流出"
        conclusion = f"主力资金已连续 {abs(main_streak)} 个有效交易日净流出。"
    else:
        stage = "多日资金分歧"
        conclusion = "多日资金方向尚未形成达到配置要求的连续模式。"

    coverage = {
        "main": sum(value is not None for value in main_values),
        "northbound": sum(value is not None for value in northbound_values),
        "margin": sum(value is not None for value in margin_values),
    }
    evidence = [
        f"历史区间：{ordered_history[0].trade_date} 至 {ordered_history[-1].trade_date}",
        f"主力连续天数：{main_streak:+d}；北向连续天数：{northbound_streak:+d}；融资余额连续变化天数：{margin_streak:+d}",
    ]
    evidence.extend(
        f"{window}日主力累计净额：{_format_optional(cumulative_flows[f'{window}d'])}；价格区间涨跌：{_format_optional(price_returns[f'{window}d'])}%"
        for window in config["windows"]
    )
    risks = ["资金流口径来自数据供应商的成交分类，不能据此确认交易主体身份或操纵意图。"]
    missing_dimensions = [name for name, count in coverage.items() if count < config["minimum_history_points"]]
    if missing_dimensions:
        risks.append(f"以下维度历史覆盖不足，相关连续性只能降级观察：{', '.join(missing_dimensions)}。")
    if divergence_type:
        risks.append("价资背离可能持续或快速修复，必须结合公告、成交量和后续交易日重新验证。")
    return SkillInsight(
        skill="资金流连续性分析",
        category="capital",
        stage=stage,
        score=clamp_score(score),
        conclusion=conclusion,
        strategy="将连续性作为现有趋势的验证证据；任一历史缺口、方向反转或新公告出现时重新计算。",
        evidence=evidence,
        risks=risks,
        details={
            "observations": len(ordered_history),
            "aligned_price_days": len(aligned_dates),
            "coverage": coverage,
            "main_streak_days": main_streak,
            "northbound_streak_days": northbound_streak,
            "margin_balance_streak_days": margin_streak,
            "cumulative_main_flow": cumulative_flows,
            "price_returns": price_returns,
            "divergence_type": divergence_type,
            "divergence_window": divergence_window,
            "source_ids": source_ids,
            "as_of": ordered_history[-1].trade_date,
        },
    )


def _signed_streak(values: list[float | None]) -> int:
    direction = 0
    count = 0
    for value in reversed(values):
        current_direction = 1 if value is not None and value > 0 else -1 if value is not None and value < 0 else 0
        if current_direction == 0 or (direction and current_direction != direction):
            break
        direction = current_direction
        count += 1
    return direction * count


def _streak_impact(streak: int, weight: float, maximum: float) -> float:
    direction = 1 if streak > 0 else -1 if streak < 0 else 0
    return direction * min(float(maximum), abs(streak) * float(weight))


def _format_optional(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "数据不足"


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
