from __future__ import annotations

from app.agents.common import clamp_score, confidence_from_score
from app.config.runtime import load_runtime_settings
from app.indicators.technical import trend_snapshot
from app.schemas.report import AgentFinding, DailyPrice


def analyze_technical(prices: list[DailyPrice]) -> AgentFinding:
    snapshot = trend_snapshot(prices)
    settings = load_runtime_settings()
    config = settings.get("scoring", "technical")
    indicator_config = settings.get("domain_knowledge", "technical")
    short_window = config["ma_short"]
    medium_window = config["ma_medium"]
    long_window = config["ma_long"]
    latest = snapshot["latest_close"] or 0.0
    ma_short = snapshot[f"ma{short_window}"] or latest
    ma_medium = snapshot[f"ma{medium_window}"] or latest
    ma_long = snapshot[f"ma{long_window}"] or latest
    period_return = snapshot[f"return_{long_window}d"] or 0.0
    vol_ratio = snapshot["volume_ratio"] or 1.0
    score = settings.get("scoring", "score_bounds", "neutral")
    score += config["trend_bonus"] if latest > ma_short > ma_medium > ma_long else -config["trend_penalty"]
    score += min(config["return_cap"], max(config["return_floor"], period_return * config["return_weight"]))
    score += config["volume_bonus"] if config["volume_low"] <= vol_ratio <= config["volume_high"] else 0
    score -= config["overheat_penalty"] if vol_ratio > config["overheat_volume"] else 0
    final_score = clamp_score(score)
    conclusion = "趋势偏多，量价较健康" if final_score >= config["strong_threshold"] else "技术面中性观察"
    if final_score <= config["weak_threshold"]:
        conclusion = "技术形态偏弱"
    return AgentFinding(
        agent="技术分析 Agent",
        conclusion=conclusion,
        score=final_score,
        confidence=confidence_from_score(final_score),
        evidence=[
            f"最新收盘 {latest:.2f}",
            f"MA{short_window}/MA{medium_window}/MA{long_window}：{ma_short:.2f}/{ma_medium:.2f}/{ma_long:.2f}",
            _format_long_window_values("MA", "ma", indicator_config["moving_average_windows"], long_window, snapshot),
            f"{long_window}日涨跌幅 {period_return:.2f}%",
            _format_long_window_values("长周期涨跌幅", "return_", indicator_config["return_windows"], long_window, snapshot, "d"),
            f"近5日量比 {vol_ratio:.2f}",
            f"MACD DIF/DEA/柱：{_format_indicator(snapshot['macd_line'])}/{_format_indicator(snapshot['macd_signal'])}/{_format_indicator(snapshot['macd_histogram'])}",
            f"BOLL 上/中/下轨：{_format_indicator(snapshot['boll_upper'])}/{_format_indicator(snapshot['boll_middle'])}/{_format_indicator(snapshot['boll_lower'])}",
            f"KDJ K/D/J：{_format_indicator(snapshot['kdj_k'])}/{_format_indicator(snapshot['kdj_d'])}/{_format_indicator(snapshot['kdj_j'])}",
            f"成交量成本区代理：VWAP {_format_indicator(snapshot['cost_vwap'])}，获利量占比 {_format_indicator(snapshot['cost_profit_volume_pct'])}%，主成本区 {snapshot['cost_dominant_zone'] or '数据不足'}。",
        ],
        risks=["短期涨幅偏快，追高性价比下降。"] if period_return > config["chase_risk_return"] else ["技术指标只描述历史价格行为，不能替代公告、流动性和规则核验。"],
        counterpoints=["均线指标滞后，需结合公告与资金流确认。"],
        invalidation_conditions=["收盘有效跌破关键均线且成交放大。", "价格趋势与资金流、公告风险出现持续背离。"],
        source_ids=["price-001"],
    )


def _format_indicator(value: float | str | None) -> str:
    return f"{value:.2f}" if isinstance(value, float) else str(value) if value is not None else "数据不足"


def _format_long_window_values(
    label: str,
    key_prefix: str,
    windows: list[int],
    base_window: int,
    snapshot: dict[str, float | str | None],
    key_suffix: str = "",
) -> str:
    long_windows = [window for window in windows if window > base_window]
    if not long_windows:
        return f"{label}：未配置更长周期"
    names = "/".join(f"{label if label == 'MA' else ''}{window}{'日' if label != 'MA' else ''}" for window in long_windows)
    values = "/".join(
        _format_indicator(snapshot[f"{key_prefix}{window}{key_suffix}"]) for window in long_windows
    )
    unit = "%" if label != "MA" else ""
    return f"{names}：{values}{unit}"
