from __future__ import annotations

from app.config.runtime import load_runtime_settings
from app.schemas.report import MoneyFlowSnapshot, SkillInsight
from app.skills.common import clamp_score


def analyze_tiered_money_flow(flow: MoneyFlowSnapshot) -> SkillInsight:
    config = load_runtime_settings().get("domain_knowledge", "money_flow_tiers")
    tiers = {
        "超大单": flow.super_large_net_inflow,
        "大单": flow.large_net_inflow,
        "中单": flow.medium_net_inflow,
        "小单": flow.small_net_inflow,
    }
    if any(value is None for value in tiers.values()):
        missing = [name for name, value in tiers.items() if value is None]
        return SkillInsight(
            "资金流分档分析", "capital", "数据不足", 0,
            "资金分档字段不完整，不能推断不同订单规模之间的行为差异。",
            "补齐同一供应商、同一交易日的超大单/大单/中单/小单净额。",
            evidence=[f"数据时间：{flow.as_of or '未知'}"], risks=[f"缺少分档：{', '.join(missing)}"],
        )
    total_absolute = sum(abs(float(value)) for value in tiers.values())
    if total_absolute < config["minimum_total_absolute_flow"]:
        return SkillInsight(
            "资金流分档分析", "capital", "信号不足", config["low_activity_score"],
            "分档资金绝对流量低于配置门槛，当前差异可能缺乏解释力。",
            "继续观察连续性，不对低流量分档做方向判断。",
            evidence=[f"分档绝对流量合计：{total_absolute:.0f}", f"数据时间：{flow.as_of or '未知'}"],
            risks=["低成交下的净流入/流出容易受少数成交影响。"],
        )
    large_side = float(flow.super_large_net_inflow) + float(flow.large_net_inflow)
    small_side = float(flow.medium_net_inflow) + float(flow.small_net_inflow)
    concentration = abs(large_side) / total_absolute
    threshold = config["divergence_threshold"]
    if large_side > threshold and small_side < -threshold:
        stage = "大单净流入/中小单净流出"
        score = config["large_in_small_out_score"]
    elif large_side < -threshold and small_side > threshold:
        stage = "大单净流出/中小单净流入"
        score = config["large_out_small_in_score"]
    elif large_side > threshold and small_side > threshold:
        stage = "各档共同净流入"
        score = config["all_in_score"]
    elif large_side < -threshold and small_side < -threshold:
        stage = "各档共同净流出"
        score = config["all_out_score"]
    else:
        stage = "分档方向分歧"
        score = config["divergent_score"]
    risks = ["分档口径由数据供应商按成交单规模估算，不能据此确认交易主体身份或操纵意图。"]
    if concentration >= config["concentration_threshold"]:
        risks.append("净流变化集中在大额订单档，需观察后续是否持续并与价格成交相互验证。")
    return SkillInsight(
        "资金流分档分析", "capital", stage, clamp_score(score),
        f"当前观察为{stage}；这是订单规模分布描述，不是主力身份认定。",
        "结合连续多个时点、价格位置、成交量和公告复核，不以单日分档直接形成行动。",
        evidence=[f"{name}净额：{float(value):.0f}" for name, value in tiers.items()] + [f"大额档绝对集中度：{concentration:.2%}", f"数据时间：{flow.as_of or '未知'}"],
        risks=risks, details={"large_side_net": large_side, "small_side_net": small_side, "large_tier_concentration": concentration},
    )
