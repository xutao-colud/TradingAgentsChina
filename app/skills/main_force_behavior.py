from __future__ import annotations

from app.indicators.technical import trend_snapshot
from app.schemas.report import DailyPrice, MoneyFlowSnapshot, SkillInsight
from app.skills.common import clamp_score


def identify_main_force_behavior(prices: list[DailyPrice], flow: MoneyFlowSnapshot) -> SkillInsight:
    snapshot = trend_snapshot(prices)
    latest = snapshot["latest_close"] or 0.0
    ma20 = snapshot["ma20"] or latest
    ret20 = snapshot["return_20d"] or 0.0
    volume_ratio = snapshot["volume_ratio"] or 1.0
    score = 50 + min(18, flow.main_net_inflow / 12_000_000) + min(10, flow.super_large_net_inflow / 15_000_000)
    score += 8 if latest >= ma20 else -8
    score += 8 if 1.05 <= volume_ratio <= 1.8 else 0
    score -= 10 if ret20 > 12 and flow.main_net_inflow < 0 else 0
    final_score = clamp_score(score)
    if flow.main_net_inflow > 0 and latest >= ma20 and volume_ratio <= 1.8:
        stage = "吸筹/拉升"
    elif flow.main_net_inflow > 0 and ret20 < 0:
        stage = "低位吸筹"
    elif flow.main_net_inflow < 0 and ret20 > 5:
        stage = "派发"
    else:
        stage = "震荡洗盘"
    return SkillInsight(
        skill="主力资金行为识别",
        category="capital",
        stage=stage,
        score=final_score,
        conclusion=f"资金行为倾向于{stage}",
        strategy="只把资金行为当作验证信号，必须结合价格位置和公告风险。",
        evidence=[
            f"主力净流入 {flow.main_net_inflow / 100_000_000:.2f} 亿元",
            f"超大单净流入 {flow.super_large_net_inflow / 100_000_000:.2f} 亿元",
            f"20日涨跌幅 {ret20:.2f}%",
            f"量比 {volume_ratio:.2f}",
            f"收盘/MA20 {latest:.2f}/{ma20:.2f}",
        ],
        risks=["资金流口径存在供应商差异，不能机械判断主力意图。"],
    )

