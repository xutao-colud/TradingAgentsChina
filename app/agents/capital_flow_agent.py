from __future__ import annotations

from app.agents.common import clamp_score, confidence_from_score
from app.config.runtime import load_runtime_settings
from app.schemas.report import AgentFinding, AshareMarketSignals, MoneyFlowSnapshot


def analyze_capital_flow(flow: MoneyFlowSnapshot, signals: AshareMarketSignals | None = None) -> AgentFinding:
    config = load_runtime_settings().get("scoring", "capital")
    score = load_runtime_settings().get("scoring", "score_bounds", "neutral")
    if flow.main_net_inflow is not None:
        score += min(config["main_cap"], flow.main_net_inflow / config["main_divisor"])
    if flow.super_large_net_inflow is not None:
        score += min(config["super_cap"], flow.super_large_net_inflow / config["super_divisor"])
    if flow.margin_balance_change is not None:
        score += min(config["margin_cap"], max(config["margin_floor"], flow.margin_balance_change * config["margin_weight"]))
    score += config["northbound_bonus"] if "流入" in flow.northbound_signal else 0
    score -= config["turnover_penalty"] if flow.turnover_rate > config["turnover_risk"] else 0
    final_score = clamp_score(score)
    evidence = [
        f"主力净流入 {flow.main_net_inflow / 100_000_000:.2f} 亿元" if flow.main_net_inflow is not None else "主力净流入：数据不可用",
        f"超大单净流入 {flow.super_large_net_inflow / 100_000_000:.2f} 亿元" if flow.super_large_net_inflow is not None else "超大单净流入：数据不可用",
        f"融资余额变化 {flow.margin_balance_change:.2f}" if flow.margin_balance_change is not None else "融资余额变化：数据不可用",
        f"北向信号：{flow.northbound_signal}",
        f"大宗交易：{flow.block_trade_signal}",
    ]
    if flow.large_net_inflow is not None:
        evidence.append(f"大单净流入 {flow.large_net_inflow / 100_000_000:.2f} 亿元")
    if flow.medium_net_inflow is not None:
        evidence.append(f"中单净流入 {flow.medium_net_inflow / 100_000_000:.2f} 亿元")
    if flow.small_net_inflow is not None:
        evidence.append(f"小单净流入 {flow.small_net_inflow / 100_000_000:.2f} 亿元")
    has_core_flow = any(
        value is not None
        for value in (flow.main_net_inflow, flow.super_large_net_inflow, flow.margin_balance_change)
    ) or "不可用" not in flow.northbound_signal
    source_ids = ["flow-001"] if has_core_flow else []
    if signals and signals.margin_financing:
        margin = signals.margin_financing
        evidence.append(f"两融明细：融资余额 {margin.margin_balance if margin.margin_balance is not None else '未披露'}，融资买入 {margin.margin_buy_amount if margin.margin_buy_amount is not None else '未披露'}。")
        source_ids.append(margin.source_id)
    if signals and signals.northbound_holding:
        northbound = signals.northbound_holding
        evidence.append(f"北向持股变动：{northbound.holding_change if northbound.holding_change is not None else '未披露'}。")
        source_ids.append(northbound.source_id)
    missing_dimensions = [
        name
        for name, value in (
            ("主力净流入", flow.main_net_inflow),
            ("超大单净流入", flow.super_large_net_inflow),
            ("融资余额变化", flow.margin_balance_change),
        )
        if value is None
    ]
    risks = ["资金流为短期指标，连续性比单日方向更重要。"]
    if missing_dimensions:
        risks.append(f"缺少资金维度：{', '.join(missing_dimensions)}；未按 0 或中性值参与评分。")
    conclusion = (
        "核心资金数据不足，当前不形成资金方向判断"
        if not has_core_flow
        else "主力资金温和流入"
        if final_score >= config["strong_threshold"]
        else "资金面中性"
    )
    return AgentFinding(
        agent="资金流 Agent",
        conclusion=conclusion,
        score=final_score,
        confidence=confidence_from_score(final_score) if has_core_flow else 0.0,
        evidence=evidence,
        risks=risks,
        counterpoints=["主力资金口径存在供应商算法差异，真实环境需交叉校验。"],
        invalidation_conditions=["主力净流入转为连续流出且成交承接走弱。", "融资、北向或大宗交易信号与主力方向持续背离。"],
        source_ids=source_ids,
    )
