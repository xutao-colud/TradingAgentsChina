from __future__ import annotations

from app.config.runtime import load_runtime_settings
from app.indicators.technical import trend_snapshot
from app.schemas.report import DailyPrice, MoneyFlowSnapshot, SkillInsight
from app.skills.common import clamp_score


def identify_main_force_behavior(prices: list[DailyPrice], flow: MoneyFlowSnapshot) -> SkillInsight:
    config = load_runtime_settings().get("scoring", "main_force_behavior")
    if flow.main_net_inflow is None:
        return SkillInsight(
            skill="主力资金行为识别",
            category="capital",
            stage="数据不足",
            score=load_runtime_settings().get("scoring", "data_readiness", "insufficient_score"),
            conclusion="主力净流入口径不可用，不能推断吸筹、洗盘、拉升或派发。",
            strategy="获取同一交易日且通过质量校验的供应商主力资金口径后再运行。",
            evidence=[f"数据时间：{flow.as_of or '未知'}"],
            risks=["缺少主力净流入字段；系统未使用 0 值代替。"],
            details={"coverage_status": "insufficient", "as_of": flow.as_of},
        )

    snapshot = trend_snapshot(prices)
    latest = snapshot["latest_close"] or 0.0
    ma20 = snapshot["ma20"] or latest
    ret20 = snapshot["return_20d"] or 0.0
    volume_ratio = snapshot["volume_ratio"] or 1.0
    score = float(config["base_score"])
    score += min(float(config["main_flow_cap"]), flow.main_net_inflow / float(config["main_flow_divisor"]))
    if flow.super_large_net_inflow is not None:
        score += min(float(config["super_flow_cap"]), flow.super_large_net_inflow / float(config["super_flow_divisor"]))
    score += float(config["trend_impact"]) if latest >= ma20 else -float(config["trend_impact"])
    score += float(config["volume_bonus"]) if float(config["volume_low"]) <= volume_ratio <= float(config["volume_high"]) else 0
    score -= float(config["divergence_penalty"]) if ret20 > float(config["overheat_return_pct"]) and flow.main_net_inflow < 0 else 0
    final_score = clamp_score(score)

    partial = flow.super_large_net_inflow is None
    if partial:
        direction = "净流入" if flow.main_net_inflow > 0 else "净流出" if flow.main_net_inflow < 0 else "方向不明"
        stage = f"单口径{direction}观察"
        conclusion = f"供应商主力资金为{direction}；超大单缺失，不能进一步归因于吸筹、洗盘、拉升或派发。"
    else:
        if flow.main_net_inflow > 0 and latest >= ma20 and volume_ratio <= float(config["volume_high"]):
            stage = "吸筹/拉升"
        elif flow.main_net_inflow > 0 and ret20 < 0:
            stage = "低位吸筹"
        elif flow.main_net_inflow < 0 and ret20 > float(config["distribution_return_pct"]):
            stage = "派发"
        else:
            stage = "震荡洗盘"
        conclusion = f"多口径资金与量价证据当前倾向于{stage}。"

    evidence = [
        f"主力净流入 {flow.main_net_inflow / float(config['display_amount_divisor']):.2f} 亿元",
        f"20日涨跌幅 {ret20:.2f}%",
        f"量比 {volume_ratio:.2f}",
        f"收盘/MA20 {latest:.2f}/{ma20:.2f}",
    ]
    evidence.insert(
        1,
        f"超大单净流入 {flow.super_large_net_inflow / float(config['display_amount_divisor']):.2f} 亿元"
        if flow.super_large_net_inflow is not None
        else "超大单净流入待核验，未按零值计分",
    )
    return SkillInsight(
        skill="主力资金行为识别",
        category="capital",
        stage=stage,
        score=final_score,
        conclusion=conclusion,
        strategy="只把资金行为作为验证信号，必须结合价格位置、连续性和公告风险。",
        evidence=evidence,
        risks=[
            "供应商定义的主力资金不是机构身份的直接证明。",
            *(["缺少超大单独立口径，当前仅展示方向性观察。"] if partial else []),
        ],
        details={
            "coverage_status": "partial" if partial else "complete",
            "source_ids": ["flow-001"],
            "as_of": flow.as_of,
        },
    )
