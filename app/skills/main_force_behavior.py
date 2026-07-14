from __future__ import annotations

from app.indicators.technical import trend_snapshot
from app.schemas.report import DailyPrice, MoneyFlowSnapshot, SkillInsight
from app.skills.common import clamp_score


def identify_main_force_behavior(prices: list[DailyPrice], flow: MoneyFlowSnapshot) -> SkillInsight:
    if flow.main_net_inflow is None or flow.super_large_net_inflow is None:
        missing = [
            name
            for name, value in (("主力净流入", flow.main_net_inflow), ("超大单净流入", flow.super_large_net_inflow))
            if value is None
        ]
        return SkillInsight(
            skill="主力资金行为识别",
            category="capital",
            stage="数据不足",
            score=0,
            conclusion="核心资金流字段不可用，不能推断吸筹、洗盘、拉升或派发。",
            strategy="获取同一交易日且通过质量校验的资金流后再运行该技能。",
            evidence=[f"数据时间：{flow.as_of or '未知'}"],
            risks=[f"缺少字段：{', '.join(missing)}；系统未使用 0 值代替。"],
        )
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
