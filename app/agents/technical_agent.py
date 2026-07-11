from __future__ import annotations

from app.agents.common import clamp_score, confidence_from_score
from app.indicators.technical import trend_snapshot
from app.schemas.report import AgentFinding, DailyPrice


def analyze_technical(prices: list[DailyPrice]) -> AgentFinding:
    snapshot = trend_snapshot(prices)
    latest = snapshot["latest_close"] or 0.0
    ma5 = snapshot["ma5"] or latest
    ma10 = snapshot["ma10"] or latest
    ma20 = snapshot["ma20"] or latest
    ret20 = snapshot["return_20d"] or 0.0
    vol_ratio = snapshot["volume_ratio"] or 1.0
    score = 50
    score += 12 if latest > ma5 > ma10 > ma20 else -6
    score += min(16, max(-12, ret20 * 1.5))
    score += 8 if 1.05 <= vol_ratio <= 1.8 else 0
    score -= 8 if vol_ratio > 2.5 else 0
    final_score = clamp_score(score)
    conclusion = "趋势偏多，量价较健康" if final_score >= 65 else "技术面中性观察"
    if final_score <= 42:
        conclusion = "技术形态偏弱"
    return AgentFinding(
        agent="技术分析 Agent",
        conclusion=conclusion,
        score=final_score,
        confidence=confidence_from_score(final_score),
        evidence=[
            f"最新收盘 {latest:.2f}",
            f"MA5/MA10/MA20：{ma5:.2f}/{ma10:.2f}/{ma20:.2f}",
            f"20日涨跌幅 {ret20:.2f}%",
            f"近5日量比 {vol_ratio:.2f}",
        ],
        risks=["短期涨幅偏快，追高性价比下降。"] if ret20 > 8 else [],
        counterpoints=["均线指标滞后，需结合公告与资金流确认。"],
        source_ids=["price-001"],
    )

