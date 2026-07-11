from __future__ import annotations

from app.agents.common import clamp_score, confidence_from_score
from app.schemas.report import AgentFinding, MoneyFlowSnapshot


def analyze_capital_flow(flow: MoneyFlowSnapshot) -> AgentFinding:
    score = 50
    score += min(18, flow.main_net_inflow / 10_000_000)
    score += min(10, flow.super_large_net_inflow / 12_000_000)
    score += min(8, max(-8, flow.margin_balance_change * 5))
    score += 6 if "流入" in flow.northbound_signal else 0
    score -= 8 if flow.turnover_rate > 8 else 0
    final_score = clamp_score(score)
    return AgentFinding(
        agent="资金流 Agent",
        conclusion="主力资金温和流入" if final_score >= 62 else "资金面中性",
        score=final_score,
        confidence=confidence_from_score(final_score),
        evidence=[
            f"主力净流入 {flow.main_net_inflow / 100_000_000:.2f} 亿元",
            f"超大单净流入 {flow.super_large_net_inflow / 100_000_000:.2f} 亿元",
            f"融资余额变化 {flow.margin_balance_change:.2f}%",
            f"北向信号：{flow.northbound_signal}",
            f"大宗交易：{flow.block_trade_signal}",
        ],
        risks=["资金流为短期指标，连续性比单日方向更重要。"],
        counterpoints=["主力资金口径来自样例数据，真实环境需校验供应商算法。"],
        source_ids=["flow-001"],
    )

