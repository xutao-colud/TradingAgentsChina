from __future__ import annotations

from statistics import median

from app.agents.common import clamp_score, confidence_from_score
from app.config.runtime import load_runtime_settings
from app.schemas.report import AgentFinding, AshareMarketSignals, DailyPrice, DragonTigerSeatRecord


def analyze_dragon_tiger(
    signals: AshareMarketSignals,
    prices: list[DailyPrice] | None = None,
    seat_history: list[DragonTigerSeatRecord] | None = None,
) -> AgentFinding:
    """Analyze disclosed seat structure without inferring undisclosed identities."""
    records = signals.dragon_tiger
    config = load_runtime_settings().get("domain_knowledge", "dragon_tiger_depth")
    source_ids = _unique([item.source_id for item in records])
    if not records:
        quality = next((item for item in signals.quality_reports if item.dataset == "dragon_tiger"), None)
        if quality and quality.status == "failed":
            conclusion = "龙虎榜原始记录未通过日期或字段质量校验，已阻止其进入分析。"
            evidence = [f"质量状态：{quality.status}；有效记录 {quality.valid_records}/{quality.checked_records}。"]
        elif quality and quality.status == "passed":
            conclusion = "数据源查询成功，但分析日期没有该股票的龙虎榜披露记录。"
            evidence = ["龙虎榜查询快照完整，返回记录为 0；不上榜不等于没有短线资金。"]
        else:
            conclusion = "未获得与分析日期对齐的龙虎榜披露记录，不能据此判断游资或机构动向。"
            evidence = ["未检索到可追溯的龙虎榜记录。"]
        return AgentFinding(
            agent="龙虎榜 Agent", conclusion=conclusion, score=config["neutral_score"], confidence=0.0,
            evidence=evidence,
            risks=["不上榜不等于没有短线资金；数据权限、披露窗口和交易日差异均可能造成缺口。"],
            counterpoints=["盘口、板块强度和公告催化仍需由独立来源验证。"],
            invalidation_conditions=["后续披露的龙虎榜明细与当前缺失状态冲突。"], source_ids=[],
        )

    seats = _deduplicate_seats([seat for record in records for seat in record.seat_records])
    net_buy = sum(item.net_buy_amount for item in records)
    institution_net = sum(item.institution_net_amount or 0.0 for item in records)
    net_impact = max(
        -float(config["net_amount_max_impact"]),
        min(float(config["net_amount_max_impact"]), net_buy / float(config["net_amount_scale"])),
    )
    institution_impact = max(
        -float(config["institution_max_impact"]),
        min(float(config["institution_max_impact"]), institution_net / float(config["net_amount_scale"])),
    )
    buy_concentration = _concentration(seats, "buy_amount", int(config["concentration_top_n"]))
    sell_concentration = _concentration(seats, "sell_amount", int(config["concentration_top_n"]))
    high_concentration = any(
        value is not None and value >= float(config["high_concentration_ratio"])
        for value in (buy_concentration, sell_concentration)
    )
    score = float(config["neutral_score"]) + net_impact + institution_impact
    if high_concentration:
        score -= float(config["concentration_risk_penalty"])
    final_score = clamp_score(score)
    direction = "净买入" if net_buy > 0 else "净卖出" if net_buy < 0 else "买卖均衡"

    seat_types = {_seat_type(item.seat_name, config) for item in seats}
    seat_type_counts = {
        seat_type: sum(_seat_type(item.seat_name, config) == seat_type for item in seats)
        for seat_type in sorted(seat_types)
    }
    known_hot_money_seat_count = sum(
        _seat_type(item.seat_name, config) == "游资席位"
        for item in seats
    )
    reason_types = [_reason_type(item.reason, config) for item in records]
    analysis_date = max(item.trade_date for item in records)
    observed_prices = [item for item in list(prices or []) if item.trade_date <= analysis_date]
    history_summary, seat_history_metrics = _seat_history_analysis(
        seats,
        list(seat_history or []),
        observed_prices,
        config,
    )
    if history_summary:
        source_ids.append("dragon-tiger-history-001")

    evidence = [
        f"上榜记录 {len(records)} 条，合计净额 {net_buy / 100_000_000:.2f} 亿元。",
        f"机构专用席位净额 {institution_net / 100_000_000:.2f} 亿元。",
        f"席位类型：{_mapping_line(seat_type_counts) if seat_type_counts else '明细未披露'}。",
        f"买方前{config['concentration_top_n']}席集中度：{_ratio_text(buy_concentration)}；卖方前{config['concentration_top_n']}席集中度：{_ratio_text(sell_concentration)}。",
        f"上榜原因分类：{', '.join(reason_types)}。",
    ]
    evidence.extend(history_summary)
    risks = [
        "龙虎榜只覆盖触发披露条件的交易，且仅披露前列席位，不能覆盖全部参与资金。",
        "券商营业部不等于特定游资；只有配置了可追溯名录的精确席位才标记为游资席位。",
        "席位上榜后的价格表现是观察性后效，不代表席位导致走势或未来可复制。",
    ]
    if high_concentration:
        risks.append("买卖金额集中于少数披露席位，单席位反向交易可能放大次日波动。")
    return AgentFinding(
        agent="龙虎榜 Agent",
        conclusion=f"披露席位合计呈{direction}；当前结论来自席位结构、集中度和历史后效，不等同于后续走势判断。",
        score=final_score,
        confidence=confidence_from_score(final_score) if seats else min(0.35, confidence_from_score(final_score)),
        evidence=evidence,
        risks=risks,
        counterpoints=["当日净买入可能是交易性仓位；若次日无承接，席位集中反而增加兑现风险。"],
        invalidation_conditions=["后续披露更正。", "席位净额方向反转。", "历史后效样本不足或价格日期无法对齐。"],
        source_ids=_unique(source_ids),
        details={
            "net_buy_amount": net_buy,
            "institution_net_amount": institution_net,
            "seat_type_counts": seat_type_counts,
            "known_hot_money_seat_count": known_hot_money_seat_count,
            "buy_concentration": buy_concentration,
            "sell_concentration": sell_concentration,
            "reason_types": reason_types,
            "seat_history_metrics": seat_history_metrics,
        },
    )


def _seat_type(name: str, config: dict[str, object]) -> str:
    known = config["known_hot_money_seats"]
    if name in known:
        return "游资席位"
    if any(keyword in name for keyword in config["institution_keywords"]):
        return "机构专用"
    if any(keyword in name for keyword in config["broker_branch_keywords"]):
        return "券商营业部"
    return "其他披露席位"


def _deduplicate_seats(seats: list[DragonTigerSeatRecord]) -> list[DragonTigerSeatRecord]:
    grouped: dict[tuple[str, str, str], list[DragonTigerSeatRecord]] = {}
    for item in seats:
        grouped.setdefault((item.trade_date, item.reason, item.seat_name), []).append(item)
    results: list[DragonTigerSeatRecord] = []
    for (_, _, _), items in grouped.items():
        sides = {item.side for item in items}
        net_values = [item.net_buy_amount for item in items if item.net_buy_amount is not None]
        results.append(DragonTigerSeatRecord(
            trade_date=items[0].trade_date,
            reason=items[0].reason,
            seat_name=items[0].seat_name,
            side=next(iter(sides)) if len(sides) == 1 else "both",
            buy_amount=max((item.buy_amount for item in items if item.buy_amount is not None), default=None),
            sell_amount=max((item.sell_amount for item in items if item.sell_amount is not None), default=None),
            net_buy_amount=max(net_values, key=abs, default=None),
            buy_rate=max((item.buy_rate for item in items if item.buy_rate is not None), default=None),
            sell_rate=max((item.sell_rate for item in items if item.sell_rate is not None), default=None),
            source_id=items[0].source_id,
        ))
    return results


def _reason_type(reason: str, config: dict[str, object]) -> str:
    for reason_type, keywords in config["reason_keywords"].items():
        if any(keyword in reason for keyword in keywords):
            return reason_type
    return "other"


def _concentration(seats: list[DragonTigerSeatRecord], field: str, top_n: int) -> float | None:
    amounts = [
        max(0.0, float(value))
        for item in seats
        if (value := getattr(item, field)) is not None
    ]
    total = sum(amounts)
    return sum(sorted(amounts, reverse=True)[:top_n]) / total if total > 0 else None


def _seat_history_analysis(
    current_seats: list[DragonTigerSeatRecord],
    history: list[DragonTigerSeatRecord],
    prices: list[DailyPrice],
    config: dict[str, object],
) -> tuple[list[str], dict[str, dict[str, object]]]:
    current_names = {item.seat_name for item in current_seats}
    if not current_names or not history or not prices:
        return [], {}
    ordered_prices = sorted(prices, key=lambda item: item.trade_date)
    price_index = {item.trade_date: index for index, item in enumerate(ordered_prices)}
    horizons = [int(item) for item in config["forward_return_horizons"]]
    events = {(item.seat_name, item.trade_date): item for item in history if item.seat_name in current_names}
    lines: list[str] = []
    metrics: dict[str, dict[str, object]] = {}
    for seat_name in sorted(current_names):
        seat_events = [item for (name, _), item in events.items() if name == seat_name]
        horizon_values: dict[int, list[float]] = {horizon: [] for horizon in horizons}
        for event in seat_events:
            index = price_index.get(event.trade_date)
            if index is None or ordered_prices[index].close == 0:
                continue
            for horizon in horizons:
                target_index = index + horizon
                if target_index < len(ordered_prices):
                    horizon_values[horizon].append(
                        (ordered_prices[target_index].close / ordered_prices[index].close - 1) * 100
                    )
        available = {horizon: values for horizon, values in horizon_values.items() if values}
        if not available:
            continue
        parts = []
        horizon_metrics: dict[str, dict[str, float | int | None]] = {}
        for horizon, values in available.items():
            part = f"{horizon}日后中位数 {median(values):+.2f}%（n={len(values)}）"
            positive_ratio: float | None = None
            if len(values) >= int(config["minimum_history_observations"]):
                positive_ratio = sum(value > 0 for value in values) / len(values)
                part += f"，正收益观察占比 {positive_ratio:.0%}"
            parts.append(part)
            horizon_metrics[str(horizon)] = {
                "observations": len(values),
                "median_return_pct": median(values),
                "positive_observation_ratio": positive_ratio,
            }
        metrics[seat_name] = {
            "seat_type": _seat_type(seat_name, config),
            "horizons": horizon_metrics,
        }
        lines.append(f"席位后效｜{seat_name}：{'；'.join(parts)}。")
    return lines, metrics


def _mapping_line(values: dict[str, int]) -> str:
    return "、".join(f"{key}{value}条" for key, value in values.items())


def _ratio_text(value: float | None) -> str:
    return f"{value:.1%}" if value is not None else "数据不足"


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
