from __future__ import annotations

from app.config.runtime import load_runtime_settings
from app.schemas.report import IntradaySnapshot, SkillInsight
from app.skills.common import clamp_score


def analyze_intraday_snapshot(snapshot: IntradaySnapshot) -> SkillInsight:
    config = load_runtime_settings().get("domain_knowledge", "intraday")
    if snapshot.data_status == "unavailable" or len(snapshot.bars) < config["minimum_bars"]:
        return SkillInsight(
            skill="盘中分时盘口分析", category="intraday", stage="数据不足", score=0,
            conclusion="缺少足量、同一交易日且带时间戳的分时/盘口数据，不能进行盘中判断。",
            strategy="等待真实分时数据恢复；不使用日线或样例数据代替盘口。",
            evidence=[f"数据状态：{snapshot.data_status}", f"分时条数：{len(snapshot.bars)}", f"数据时间：{snapshot.as_of}"],
            risks=list(snapshot.unavailable_reasons), details={"source_ids": snapshot.source_ids},
        )
    bars = sorted(snapshot.bars, key=lambda item: item.timestamp)
    total_volume = sum(max(0.0, item.volume) for item in bars)
    total_amount = sum(max(0.0, item.amount) for item in bars)
    vwap = total_amount / total_volume if total_volume > 0 else None
    period = max(1, int(config["minute_period"]))
    opening_count = max(1, int(config["opening_minutes"]) // period)
    closing_count = max(1, int(config["closing_minutes"]) // period)
    opening_share = _volume_share(bars[:opening_count], total_volume)
    closing_share = _volume_share(bars[-closing_count:], total_volume)
    recent_count = min(3, max(1, len(bars) // 2))
    recent_average = sum(item.volume for item in bars[-recent_count:]) / recent_count
    prior_rows = bars[:-recent_count]
    prior_average = sum(item.volume for item in prior_rows) / len(prior_rows) if prior_rows else None
    volume_ratio = recent_average / prior_average if prior_average not in {None, 0} else None
    bid_volume = sum(item.volume for item in snapshot.bids)
    ask_volume = sum(item.volume for item in snapshot.asks)
    book_total = bid_volume + ask_volume
    imbalance = (bid_volume - ask_volume) / book_total if book_total > 0 else None
    latest = bars[-1].close
    score = float(config["base_score"])
    if vwap not in {None, 0}:
        cap = float(config["price_vwap_score_cap"])
        score += max(-cap, min(cap, (latest / vwap - 1) * 100 * config["price_vwap_weight"]))
    if volume_ratio is not None:
        cap = float(config["volume_score_cap"])
        score += max(-cap, min(cap, (volume_ratio - 1) * config["volume_score_weight"]))
    if imbalance is not None:
        cap = float(config["imbalance_score_cap"])
        score += max(-cap, min(cap, imbalance * config["imbalance_score_weight"]))
    neutral_band = config["imbalance_neutral_band"]
    if imbalance is None:
        stage = "仅分时可用"
    elif imbalance > neutral_band and vwap is not None and latest >= vwap:
        stage = "买方承接偏强"
    elif imbalance < -neutral_band and vwap is not None and latest <= vwap:
        stage = "卖方压力偏强"
    else:
        stage = "盘口分歧"
    concentration = config["volume_concentration_threshold"]
    risks = ["五档委托可以撤单，委托不平衡不等于真实成交，也不能证明特定主力意图。"]
    if opening_share >= concentration or closing_share >= concentration:
        risks.append("成交量集中在开盘或尾盘，需防止单一时段扭曲全天判断。")
    return SkillInsight(
        skill="盘中分时盘口分析", category="intraday", stage=stage, score=clamp_score(score),
        conclusion=f"当前可观察到的分时/盘口状态为：{stage}。",
        strategy="仅将分时与盘口作为当日证据；结合市场状态、涨跌停可成交性和公告风险复核。",
        evidence=[
            f"数据时间：{snapshot.as_of}",
            f"最新价/VWAP：{latest:.3f}/{vwap:.3f}" if vwap is not None else f"最新价：{latest:.3f}，VWAP不可计算",
            f"早盘/尾盘成交量占比：{opening_share:.2%}/{closing_share:.2%}",
            f"近期/此前分时均量比：{volume_ratio:.2f}" if volume_ratio is not None else "分时均量比不可计算",
            f"五档买卖委托不平衡：{imbalance:.2%}" if imbalance is not None else "五档委托数据不足",
        ],
        risks=risks,
        details={"vwap": vwap, "opening_volume_share": opening_share, "closing_volume_share": closing_share,
                 "recent_volume_ratio": volume_ratio, "order_book_imbalance": imbalance, "source_ids": snapshot.source_ids},
    )


def _volume_share(rows: list, total_volume: float) -> float:
    return sum(max(0.0, item.volume) for item in rows) / total_volume if total_volume > 0 else 0.0
