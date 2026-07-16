from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from app.config.runtime import load_runtime_settings
from app.schemas.report import MarketContext


@dataclass(frozen=True)
class MarketBreadthFacts:
    median_stock_change_pct: float | None
    amount_weighted_change_pct: float | None
    top_amount_concentration_pct: float | None


@dataclass(frozen=True)
class MarketBreadthConfirmation:
    stage: str
    score_adjustment: float
    confidence_cap: float
    evidence: list[str]
    risks: list[str]
    counterpoints: list[str]
    missing_fields: list[str]


def calculate_market_breadth_facts(
    pct_changes: list[float],
    amounts: list[float],
    *,
    top_amount_count: int,
) -> MarketBreadthFacts:
    """Calculate observable cross-section facts without interpreting direction."""
    if not pct_changes or len(pct_changes) != len(amounts):
        return MarketBreadthFacts(None, None, None)
    valid_pairs = [
        (float(change), float(amount))
        for change, amount in zip(pct_changes, amounts)
        if amount >= 0
    ]
    if not valid_pairs:
        return MarketBreadthFacts(None, None, None)
    total_amount = sum(amount for _, amount in valid_pairs)
    weighted = (
        sum(change * amount for change, amount in valid_pairs) / total_amount
        if total_amount > 0
        else None
    )
    concentration = (
        sum(sorted((amount for _, amount in valid_pairs), reverse=True)[:top_amount_count])
        / total_amount
        * 100
        if total_amount > 0 and top_amount_count > 0
        else None
    )
    return MarketBreadthFacts(
        median_stock_change_pct=float(median(change for change, _ in valid_pairs)),
        amount_weighted_change_pct=weighted,
        top_amount_concentration_pct=concentration,
    )


def evaluate_market_breadth_confirmation(context: MarketContext) -> MarketBreadthConfirmation:
    """Cross-check index direction with equal-weight, turnover and limit feedback."""
    config = load_runtime_settings().get("domain_knowledge", "market_breadth_confirmation")
    required = {
        "index_change_pct": context.index_change_pct,
        "median_stock_change_pct": context.median_stock_change_pct,
        "amount_weighted_change_pct": context.amount_weighted_change_pct,
        "top_amount_concentration_pct": context.top_amount_concentration_pct,
        "advancers": context.advancers,
        "decliners": context.decliners,
        "limit_up_count": context.limit_up_count,
        "limit_down_count": context.limit_down_count,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing or context.data_status != "verified":
        return MarketBreadthConfirmation(
            stage="数据不足",
            score_adjustment=float(config["insufficient_adjustment"]),
            confidence_cap=float(config["insufficient_confidence_cap"]),
            evidence=[f"缺失字段：{', '.join(missing) if missing else '无'}", f"数据时间：{context.as_of or '未知'}"],
            risks=["指数、个股中位数、成交额加权涨跌和涨跌停反馈未形成完整交叉核验链。"],
            counterpoints=["不能仅凭指数或上涨家数单独判断市场风险偏好。"],
            missing_fields=missing,
        )

    advancers = int(context.advancers)
    decliners = int(context.decliners)
    breadth_ratio = advancers / max(1, advancers + decliners) * 100
    index_direction = _direction(float(context.index_change_pct), float(config["neutral_band_pct"]))
    median_direction = _direction(float(context.median_stock_change_pct), float(config["neutral_band_pct"]))
    weighted_direction = _direction(float(context.amount_weighted_change_pct), float(config["neutral_band_pct"]))
    breadth_direction = (
        1 if breadth_ratio >= float(config["breadth_bullish_pct"])
        else -1 if breadth_ratio <= float(config["breadth_bearish_pct"])
        else 0
    )
    limit_balance = int(context.limit_up_count) - int(context.limit_down_count)
    limit_direction = (
        1 if limit_balance >= int(config["minimum_limit_balance"])
        else -1 if limit_balance <= -int(config["minimum_limit_balance"])
        else 0
    )
    core_directions = [median_direction, breadth_direction]
    concentration = float(context.top_amount_concentration_pct)
    divergence = abs(float(context.index_change_pct) - float(context.median_stock_change_pct))
    weighted_divergence = (
        index_direction != 0
        and weighted_direction == index_direction
        and any(direction == -index_direction for direction in core_directions)
    )
    if weighted_divergence or (
        index_direction != 0
        and any(direction == -index_direction for direction in core_directions)
        and divergence >= float(config["index_median_divergence_pct"])
    ):
        stage = "权重背离"
    elif (
        index_direction != 0
        and all(direction in {0, index_direction} for direction in core_directions)
        and limit_direction in {0, index_direction}
    ):
        stage = "一致确认"
    else:
        stage = "局部分化"

    stage_config = config["stages"][stage]
    risks: list[str] = []
    if stage == "权重背离":
        risks.append("指数方向与个股中位数或上涨家数相反，少数高成交权重股可能放大指数表象。")
    elif stage == "局部分化":
        risks.append("指数、市场广度与涨跌停反馈未完全同向，当前市场状态只能按分化处理。")
    if concentration >= float(config["concentration_warning_pct"]):
        risks.append(
            f"成交额前 {int(config['top_amount_count'])} 只股票占比 {concentration:.1f}%，市场成交集中度偏高。"
        )
    return MarketBreadthConfirmation(
        stage=stage,
        score_adjustment=float(stage_config["score_adjustment"]),
        confidence_cap=float(stage_config["confidence_cap"]),
        evidence=[
            f"{context.index_name} {float(context.index_change_pct):+.2f}%",
            f"全市场个股涨跌中位数 {float(context.median_stock_change_pct):+.2f}%",
            f"成交额加权涨跌 {float(context.amount_weighted_change_pct):+.2f}%",
            f"上涨占比 {breadth_ratio:.1f}%（{advancers}/{advancers + decliners}）",
            f"涨停/跌停 {context.limit_up_count}/{context.limit_down_count}",
            f"成交额前 {int(config['top_amount_count'])} 只集中度 {concentration:.1f}%",
            f"数据时间：{context.as_of}",
        ],
        risks=risks,
        counterpoints=["单日横截面只验证当日市场一致性，不能替代连续情绪历史和中期趋势。"],
        missing_fields=[],
    )


def _direction(value: float, neutral_band: float) -> int:
    if value > neutral_band:
        return 1
    if value < -neutral_band:
        return -1
    return 0
