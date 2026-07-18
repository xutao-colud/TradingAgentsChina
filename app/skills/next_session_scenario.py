from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from app.config.runtime import load_runtime_settings
from app.indicators.technical import average_true_range, moving_average, pct_change
from app.schemas.report import DailyPrice, SkillInsight


@dataclass(frozen=True)
class _HistoricalOutcome:
    signal_date: str
    outcome_date: str
    signature: tuple[str, str, str]
    return_pct: float


def analyze_next_session_scenario(
    prices: list[DailyPrice], data_readiness: SkillInsight | None = None
) -> SkillInsight:
    """Describe next-session historical frequencies without treating them as a forecast."""
    config = load_runtime_settings().get("domain_knowledge", "next_session_scenario")
    ordered = _valid_ordered_prices(prices)
    source_rejection = _price_source_rejection(data_readiness)
    if source_rejection:
        return _insufficient(ordered, source_rejection)
    minimum_feature_bars = int(config["minimum_feature_bars"])
    if len(ordered) < minimum_feature_bars + 1:
        return _insufficient(
            ordered,
            f"有效日线仅 {len(ordered)} 条，无法形成无前视偏差的次日结果样本。",
        )

    outcomes: list[_HistoricalOutcome] = []
    for index in range(minimum_feature_bars - 1, len(ordered) - 1):
        history = ordered[: index + 1]
        signature = _market_signature(history, config)
        current_close = ordered[index].close
        if signature is None or current_close <= 0:
            continue
        outcomes.append(
            _HistoricalOutcome(
                signal_date=ordered[index].trade_date,
                outcome_date=ordered[index + 1].trade_date,
                signature=signature,
                return_pct=pct_change(current_close, ordered[index + 1].close),
            )
        )

    current_signature = _market_signature(ordered, config)
    if current_signature is None:
        return _insufficient(ordered, "当前价格历史不足以计算趋势、动量和波动状态。")
    similar = [item for item in outcomes if item.signature == current_signature]
    if len(similar) >= int(config["minimum_similar_samples"]):
        selected = similar
        sample_mode = "similar"
        stage = "相似状态样本"
    elif len(outcomes) >= int(config["minimum_baseline_samples"]):
        selected = outcomes
        sample_mode = "baseline"
        stage = "全样本基准（相似样本不足）"
    else:
        return _insufficient(
            ordered,
            f"可用次日结果样本仅 {len(outcomes)} 个，低于配置门槛 {config['minimum_baseline_samples']} 个。",
            similar_count=len(similar),
            current_signature=current_signature,
        )

    flat_band = float(config["flat_band_pct"])
    red = [item for item in selected if item.return_pct > flat_band]
    green = [item for item in selected if item.return_pct < -flat_band]
    flat = [item for item in selected if -flat_band <= item.return_pct <= flat_band]
    total = len(selected)
    red_rate = len(red) / total * 100
    green_rate = len(green) / total * 100
    flat_rate = len(flat) / total * 100
    returns = [item.return_pct for item in selected]
    z_score = float(config["wilson_z"])
    red_interval = _wilson_interval(len(red), total, z_score)
    green_interval = _wilson_interval(len(green), total, z_score)
    signature_text = _signature_text(current_signature)
    return SkillInsight(
        skill="次日红绿盘情景观察",
        category="scenario",
        stage=stage,
        score=int(config["neutral_score"]),
        conclusion=(
            f"历史观察样本中，次日红盘 {red_rate:.1f}%、平盘 {flat_rate:.1f}%、绿盘 {green_rate:.1f}%；"
            "这是条件频率，不是明日涨跌预测。"
        ),
        strategy="仅把该统计用于检验当前研究剧本，不据此生成买卖指令；必须同时核验市场状态、公告和盘中跳空风险。",
        evidence=[
            f"当前状态：{signature_text}",
            f"样本口径：{stage}，样本数 {total}（相似状态 {len(similar)}）",
            f"样本区间：{selected[0].signal_date} 至 {selected[-1].outcome_date}",
            f"次日收益均值/中位数：{statistics.fmean(returns):.2f}%/{statistics.median(returns):.2f}%",
            f"数据时间：{ordered[-1].trade_date}",
        ],
        risks=[
            "历史条件频率不等于未来概率，样本内结构变化、停复牌、涨跌停和隔夜公告都可能使统计失效。",
            "若使用全样本基准，说明相似状态样本未达到门槛，不能据此形成方向性结论。",
            f"红盘率 Wilson 区间约 {red_interval[0]:.1f}%–{red_interval[1]:.1f}%，绿盘率约 {green_interval[0]:.1f}%–{green_interval[1]:.1f}%，存在抽样误差。",
        ],
        details={
            "mode": "next_session_scenario",
            "admitted": False,
            "available": True,
            "observational_only": True,
            "no_forward_lookahead": True,
            "sample_mode": sample_mode,
            "sample_size": total,
            "similar_sample_size": len(similar),
            "sample_start": selected[0].signal_date,
            "sample_end": selected[-1].outcome_date,
            "red_rate_pct": round(red_rate, 2),
            "flat_rate_pct": round(flat_rate, 2),
            "green_rate_pct": round(green_rate, 2),
            "red_count": len(red),
            "flat_count": len(flat),
            "green_count": len(green),
            "red_wilson_interval_pct": [round(red_interval[0], 2), round(red_interval[1], 2)],
            "green_wilson_interval_pct": [round(green_interval[0], 2), round(green_interval[1], 2)],
            "mean_return_pct": round(statistics.fmean(returns), 4),
            "median_return_pct": round(statistics.median(returns), 4),
            "flat_band_pct": flat_band,
            "signature": {
                "trend": current_signature[0],
                "momentum": current_signature[1],
                "volatility": current_signature[2],
            },
            "source_ids": ["price-001"],
            "as_of": ordered[-1].trade_date,
            "invalidation_conditions": [
                "分析日后出现未纳入样本的重大公告、停复牌或交易制度变化",
                "当前状态签名在下一交易日前发生明显变化",
                "数据复权口径、交易日连续性或价格质量校验失败",
            ],
        },
    )


def _market_signature(prices: list[DailyPrice], config: dict[str, object]) -> tuple[str, str, str] | None:
    trend_window = int(config["trend_window"])
    momentum_window = int(config["momentum_window"])
    atr_window = int(config["atr_window"])
    required = max(trend_window, momentum_window + 1, atr_window + 1)
    if len(prices) < required or prices[-1].close <= 0:
        return None
    closes = [item.close for item in prices]
    trend_average = moving_average(closes, trend_window)
    atr = average_true_range(prices, atr_window)
    if trend_average is None or atr is None:
        return None
    trend = "above_ma" if closes[-1] >= trend_average else "below_ma"
    momentum_return = pct_change(closes[-momentum_window - 1], closes[-1])
    momentum = "positive" if momentum_return >= 0 else "negative"
    volatility_pct = atr / closes[-1] * 100
    if volatility_pct < float(config["volatility_low_pct"]):
        volatility = "low"
    elif volatility_pct > float(config["volatility_high_pct"]):
        volatility = "high"
    else:
        volatility = "medium"
    return trend, momentum, volatility


def _valid_ordered_prices(prices: list[DailyPrice]) -> list[DailyPrice]:
    by_date = {
        item.trade_date: item
        for item in prices
        if item.trade_date and item.close > 0 and item.high >= item.low and item.volume >= 0
    }
    return [by_date[key] for key in sorted(by_date)]


def _wilson_interval(successes: int, total: int, z_score: float) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    proportion = successes / total
    denominator = 1 + z_score**2 / total
    center = (proportion + z_score**2 / (2 * total)) / denominator
    margin = z_score * math.sqrt(
        (proportion * (1 - proportion) + z_score**2 / (4 * total)) / total
    ) / denominator
    return max(0.0, center - margin) * 100, min(1.0, center + margin) * 100


def _signature_text(signature: tuple[str, str, str]) -> str:
    labels = {
        "above_ma": "收盘在 MA20 上方",
        "below_ma": "收盘在 MA20 下方",
        "positive": "5 日动量非负",
        "negative": "5 日动量为负",
        "low": "低波动",
        "medium": "中波动",
        "high": "高波动",
    }
    return "、".join(labels.get(item, item) for item in signature)


def _insufficient(
    prices: list[DailyPrice],
    reason: str,
    similar_count: int = 0,
    current_signature: tuple[str, str, str] | None = None,
) -> SkillInsight:
    config = load_runtime_settings().get("domain_knowledge", "next_session_scenario")
    return SkillInsight(
        skill="次日红绿盘情景观察",
        category="scenario",
        stage="样本不足",
        score=int(config["neutral_score"]),
        conclusion=reason,
        strategy="继续积累经质量校验的连续复权日线；样本不足时不显示红盘率或绿盘率。",
        evidence=[f"当前有效日线：{len(prices)} 条", f"相似状态样本：{similar_count} 个"],
        risks=["缺少足够样本时输出百分比会制造虚假精度，因此本次拒绝估计。"],
        details={
            "mode": "next_session_scenario",
            "admitted": False,
            "observational_only": True,
            "available": False,
            "sample_size": 0,
            "similar_sample_size": similar_count,
            "signature": current_signature,
            "source_ids": ["price-001"] if prices else [],
            "as_of": prices[-1].trade_date if prices else None,
        },
    )


def _price_source_rejection(data_readiness: SkillInsight | None) -> str | None:
    if data_readiness is None:
        return None
    details = data_readiness.details or {}
    if "price-001" in set(details.get("sample_source_ids") or []):
        return "日线来自样例数据，禁止据此展示红盘率或绿盘率。"
    if "price-001" in set(details.get("missing_source_ids") or []) | set(details.get("unavailable_source_ids") or []):
        return "缺少可核验的日线来源 price-001，禁止据此展示红盘率或绿盘率。"
    blocking = " ".join(str(item) for item in details.get("blocking_quality_failures") or [])
    if "daily_prices" in blocking:
        return "日线质量门禁失败，禁止据此展示红盘率或绿盘率。"
    return None
