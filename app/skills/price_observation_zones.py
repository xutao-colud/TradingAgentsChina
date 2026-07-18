from __future__ import annotations

import re
from typing import Any

from app.config.runtime import load_runtime_settings
from app.indicators.technical import average_true_range, trend_snapshot
from app.schemas.report import DailyPrice, FundamentalSnapshot, SkillInsight


def analyze_price_observation_zones(
    prices: list[DailyPrice],
    fundamentals: FundamentalSnapshot | None = None,
    data_readiness: SkillInsight | None = None,
) -> SkillInsight:
    """Build evidence-based observation zones; never emit entry or exit orders."""
    config = load_runtime_settings().get("domain_knowledge", "price_observation_zones")
    ordered = _valid_ordered_prices(prices)
    source_rejection = _price_source_rejection(data_readiness)
    if source_rejection:
        return _insufficient(ordered, source_rejection)
    minimum_short = int(config["minimum_short_bars"])
    if len(ordered) < minimum_short:
        return _insufficient(ordered, f"有效日线仅 {len(ordered)} 条，短线观察区至少需要 {minimum_short} 条。")

    latest = ordered[-1].close
    atr = average_true_range(ordered, int(config["atr_window"]))
    if atr is None or atr <= 0:
        return _insufficient(ordered, "ATR 无法计算，拒绝生成没有波动尺度的价格区间。")
    snapshot = trend_snapshot(ordered)
    dominant_zone = _parse_zone(snapshot.get("cost_dominant_zone"))
    short_sample = ordered[-int(config["short_lookback"]):]
    pivot_sample = ordered[-int(config["short_pivot_window"]):]
    short_support_candidates = _numbers(
        snapshot.get("boll_lower"),
        snapshot.get("ma20"),
        snapshot.get("cost_vwap"),
        min(item.low for item in pivot_sample),
        min(item.low for item in short_sample),
        *(dominant_zone or ()),
    )
    short_resistance_candidates = _numbers(
        snapshot.get("boll_upper"),
        snapshot.get("ma20"),
        snapshot.get("cost_vwap"),
        max(item.high for item in pivot_sample),
        max(item.high for item in short_sample),
        *(dominant_zone or ()),
    )
    short = _build_horizon(
        latest,
        atr,
        short_support_candidates,
        short_resistance_candidates,
        float(config["short_zone_atr_half_width"]),
        float(config["invalidation_atr_distance"]),
        float(config["breakout_atr_distance"]),
    )

    medium: dict[str, Any]
    minimum_medium = int(config["minimum_medium_bars"])
    if len(ordered) >= minimum_medium:
        medium_sample = ordered[-int(config["medium_lookback"]):]
        medium = _build_horizon(
            latest,
            atr,
            _numbers(
                snapshot.get("ma60"),
                snapshot.get("cost_vwap"),
                min(item.low for item in medium_sample),
                *(dominant_zone or ()),
            ),
            _numbers(
                snapshot.get("ma60"),
                snapshot.get("cost_vwap"),
                max(item.high for item in medium_sample),
                *(dominant_zone or ()),
            ),
            float(config["medium_zone_atr_half_width"]),
            float(config["invalidation_atr_distance"]),
            float(config["breakout_atr_distance"]),
        )
        medium["available"] = bool(medium["support_zone"] or medium["resistance_zone"])
        medium["reason"] = None
    else:
        medium = {
            "available": False,
            "support_zone": None,
            "resistance_zone": None,
            "invalidation_below": None,
            "confirmation_above": None,
            "reason": f"有效日线少于 {minimum_medium} 条。",
        }

    long_term = _long_term_valuation_anchor(fundamentals, int(config["minimum_long_valuation_points"]))
    stage = "短中期区间可用" if medium["available"] else "短线区间可用"
    evidence = [
        f"最新收盘价 {latest:.2f}，ATR({config['atr_window']}) {atr:.3f}",
        f"短线低位观察区：{_format_zone(short['support_zone'])}",
        f"短线反弹压力区：{_format_zone(short['resistance_zone'])}",
        f"成本密集区：{snapshot.get('cost_dominant_zone') or '未取得'}",
        f"数据时间：{ordered[-1].trade_date}",
    ]
    return SkillInsight(
        skill="多周期价格观察区间",
        category="price_zones",
        stage=stage,
        score=int(config["neutral_score"]),
        conclusion=(
            f"短线低位观察区 {_format_zone(short['support_zone'])}，"
            f"反弹压力区 {_format_zone(short['resistance_zone'])}；区间用于观察支撑与压力，不是买入或卖出指令。"
        ),
        strategy="到达观察区后仍需等待量价、市场状态和公告证据确认；跌破失效位或突破确认位时重新计算，不机械执行。",
        evidence=evidence,
        risks=[
            "ATR、均线、布林带和历史高低点都是滞后统计；跳空、涨跌停、停牌或重大公告会使区间立即失效。",
            "价格触及支撑不代表必然反弹，触及压力也不代表必然回落；必须结合成交和资金连续性复核。",
            "长线价格必须由可核验的估值历史、盈利质量和行业周期共同锚定，不能用短线技术位替代。",
        ],
        details={
            "mode": "price_observation_zones",
            "admitted": False,
            "available": True,
            "observational_only": True,
            "current_price": round(latest, 2),
            "atr": round(atr, 4),
            "short_term": short,
            "medium_term": medium,
            "long_term": long_term,
            "inputs": {
                "boll_lower": _round_or_none(snapshot.get("boll_lower")),
                "boll_upper": _round_or_none(snapshot.get("boll_upper")),
                "ma20": _round_or_none(snapshot.get("ma20")),
                "ma60": _round_or_none(snapshot.get("ma60")),
                "cost_vwap": _round_or_none(snapshot.get("cost_vwap")),
                "dominant_cost_zone": snapshot.get("cost_dominant_zone"),
            },
            "source_ids": ["price-001"],
            "as_of": ordered[-1].trade_date,
            "invalidation_conditions": [
                f"收盘有效跌破 {_format_price(short['invalidation_below'])}",
                "出现重大公告、停牌、除权除息或复权口径变化",
                "市场状态或波动率显著改变，当前 ATR 区间不再适用",
            ],
        },
    )


def _build_horizon(
    latest: float,
    atr: float,
    supports: list[float],
    resistances: list[float],
    half_width_atr: float,
    invalidation_atr: float,
    breakout_atr: float,
) -> dict[str, Any]:
    minimum_distance = atr * breakout_atr
    support = max((value for value in supports if value <= latest - minimum_distance), default=None)
    resistance = min((value for value in resistances if value >= latest + minimum_distance), default=None)
    half_width = atr * half_width_atr
    support_zone = _zone(support, half_width, ceiling=latest) if support is not None else None
    resistance_zone = _zone(resistance, half_width, floor=latest) if resistance is not None else None
    return {
        "available": bool(support_zone or resistance_zone),
        "support_center": _round_or_none(support),
        "support_zone": support_zone,
        "resistance_center": _round_or_none(resistance),
        "resistance_zone": resistance_zone,
        "invalidation_below": _round_or_none(support - atr * invalidation_atr) if support is not None else None,
        "confirmation_above": _round_or_none(resistance + atr * breakout_atr) if resistance is not None else None,
    }


def _long_term_valuation_anchor(
    fundamentals: FundamentalSnapshot | None, minimum_points: int
) -> dict[str, Any]:
    available_metrics = []
    if fundamentals:
        available_metrics = [
            name
            for name, value in (("PE TTM", fundamentals.pe_ttm), ("PB", fundamentals.pb))
            if value is not None
        ]
    return {
        "available": False,
        "target_zone": None,
        "available_metrics": available_metrics,
        "required_valuation_points": minimum_points,
        "reason": (
            f"尚无至少 {minimum_points} 个公告时点的历史估值与盈利预测序列；"
            "拒绝用短线技术位冒充长期目标价。"
        ),
    }


def _parse_zone(value: object) -> tuple[float, float] | None:
    if not isinstance(value, str):
        return None
    numbers = [float(item) for item in re.findall(r"\d+(?:\.\d+)?", value)]
    if not numbers:
        return None
    if len(numbers) == 1:
        return numbers[0], numbers[0]
    return min(numbers[0], numbers[1]), max(numbers[0], numbers[1])


def _numbers(*values: object) -> list[float]:
    result: list[float] = []
    for value in values:
        if isinstance(value, (int, float)) and value > 0:
            result.append(float(value))
    return result


def _zone(
    center: float,
    half_width: float,
    floor: float | None = None,
    ceiling: float | None = None,
) -> list[float]:
    lower = max(0.01, center - half_width)
    upper = center + half_width
    if floor is not None:
        lower = max(lower, floor)
    if ceiling is not None:
        upper = min(upper, ceiling)
    return [round(lower, 2), round(max(lower, upper), 2)]


def _round_or_none(value: object) -> float | None:
    return round(float(value), 2) if isinstance(value, (int, float)) else None


def _format_zone(zone: object) -> str:
    if isinstance(zone, list) and len(zone) == 2:
        return f"{float(zone[0]):.2f}–{float(zone[1]):.2f}"
    return "暂无可核验区间"


def _format_price(value: object) -> str:
    return f"{float(value):.2f}" if isinstance(value, (int, float)) else "未计算"


def _valid_ordered_prices(prices: list[DailyPrice]) -> list[DailyPrice]:
    by_date = {
        item.trade_date: item
        for item in prices
        if item.trade_date and item.close > 0 and item.high >= item.low and item.volume >= 0
    }
    return [by_date[key] for key in sorted(by_date)]


def _insufficient(prices: list[DailyPrice], reason: str) -> SkillInsight:
    config = load_runtime_settings().get("domain_knowledge", "price_observation_zones")
    return SkillInsight(
        skill="多周期价格观察区间",
        category="price_zones",
        stage="数据不足",
        score=int(config["neutral_score"]),
        conclusion=reason,
        strategy="补齐连续复权日线后重新计算；数据不足时不生成低吸、高抛或长期目标价。",
        evidence=[f"当前有效日线：{len(prices)} 条"],
        risks=["缺少波动率和关键价位证据时给出具体价格会产生虚假精度，因此本次拒绝估计。"],
        details={
            "mode": "price_observation_zones",
            "admitted": False,
            "observational_only": True,
            "available": False,
            "source_ids": ["price-001"] if prices else [],
            "as_of": prices[-1].trade_date if prices else None,
        },
    )


def _price_source_rejection(data_readiness: SkillInsight | None) -> str | None:
    if data_readiness is None:
        return None
    details = data_readiness.details or {}
    if "price-001" in set(details.get("sample_source_ids") or []):
        return "日线来自样例数据，禁止据此生成价格观察区间。"
    if "price-001" in set(details.get("missing_source_ids") or []) | set(details.get("unavailable_source_ids") or []):
        return "缺少可核验的日线来源 price-001，禁止据此生成价格观察区间。"
    blocking = " ".join(str(item) for item in details.get("blocking_quality_failures") or [])
    if "daily_prices" in blocking:
        return "日线质量门禁失败，禁止据此生成价格观察区间。"
    return None
