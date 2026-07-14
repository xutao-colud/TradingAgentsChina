from __future__ import annotations

from app.config.runtime import load_runtime_settings
from app.schemas.report import DailyPrice, SkillInsight
from app.skills.common import clamp_score


def analyze_turnover_continuity(prices: list[DailyPrice]) -> SkillInsight:
    config = load_runtime_settings().get("domain_knowledge", "turnover_continuity")
    observations = [item for item in prices if item.turnover_rate is not None]
    minimum = int(config["minimum_history_points"])
    if len(observations) < minimum:
        return _insufficient(
            prices,
            "有效换手率历史不足，不能判断资金活跃度的连续变化。",
            [f"有效观察 {len(observations)} 个，最低要求 {minimum} 个"],
        )

    windows = sorted(int(item) for item in config["windows"] if int(item) <= len(observations))
    if not windows:
        return _insufficient(prices, "配置的换手窗口没有足够历史，不能计算连续变化。", [])
    latest = float(observations[-1].turnover_rate)
    changes: dict[str, float] = {}
    for window in windows:
        values = [float(item.turnover_rate) for item in observations[-window:]]
        baseline = sum(values[:-1]) / max(1, len(values) - 1)
        if baseline <= 0:
            return _insufficient(
                prices,
                "换手率历史基线不为正，不能生成连续变化或中性信号。",
                [f"{window} 日窗口基线：{baseline}"],
            )
        changes[f"{window}d_change_pct"] = (latest / baseline - 1) * 100
    primary_change = changes[f"{windows[0]}d_change_pct"]
    flat = float(config["flat_change_pct"])
    stage = "持续放大" if primary_change > flat else "持续收缩" if primary_change < -flat else "换手平稳"

    confirmation_window = min(int(config["price_confirmation_window"]), len(observations))
    start_close = observations[-confirmation_window].close
    if start_close <= 0:
        return _insufficient(prices, "价格确认窗口的起始收盘价无效，不能判断量价背离。", [])
    price_change = (observations[-1].close / start_close - 1) * 100
    divergence_threshold = float(config["price_divergence_threshold_pct"])
    divergence = (
        "放量滞涨"
        if primary_change > flat and price_change < -divergence_threshold
        else "缩量上涨"
        if primary_change < -flat and price_change > divergence_threshold
        else "无明显背离"
    )
    score = float(config["neutral_score"])
    impact = min(
        float(config["trend_score_impact"]),
        abs(primary_change) / float(config["change_score_scale_pct"]) * float(config["trend_score_impact"]),
    )
    score += impact if primary_change > flat else -impact if primary_change < -flat else 0
    if latest >= float(config["extreme_turnover_rate_pct"]):
        score -= impact
    final_score = clamp_score(score)
    return SkillInsight(
        skill="换手率连续变化",
        category="capital",
        stage=stage,
        score=final_score,
        conclusion=f"换手率相对近期均值{stage}，价格配合为{divergence}。",
        strategy="把换手变化作为资金参与度证据，与价格趋势和资金分档共同解释。",
        evidence=[
            f"最新换手率 {latest:.2f}%",
            *[f"{key.replace('_change_pct', '')} 相对变化 {value:.2f}%" for key, value in changes.items()],
            f"同期价格变化 {price_change:.2f}%",
            f"数据时间：{observations[-1].trade_date}",
        ],
        risks=[
            "高换手既可能是承接也可能是派发，方向必须由价格和资金流确认。",
            "自由流通股本变化会改变换手率的可比性。",
        ],
        details={
            "mode": "turnover_continuity",
            "admitted": True,
            "latest_turnover_rate": latest,
            "price_change_pct": price_change,
            "divergence": divergence,
            **changes,
            "source_ids": ["price-001"],
            "as_of": observations[-1].trade_date,
        },
    )


def _insufficient(prices: list[DailyPrice], conclusion: str, evidence: list[str]) -> SkillInsight:
    return SkillInsight(
        skill="换手率连续变化",
        category="capital",
        stage="数据不足",
        score=load_runtime_settings().get("scoring", "data_readiness", "insufficient_score"),
        conclusion=conclusion,
        strategy="补齐并校验每日换手率后重算，不把缺失或无效基线写成零。",
        evidence=evidence,
        risks=["成交价量存在但 daily_basic 缺失或异常时，换手趋势必须保持不可用。"],
        details={
            "mode": "turnover_continuity",
            "admitted": False,
            "source_ids": [],
            "as_of": prices[-1].trade_date if prices else None,
        },
    )
