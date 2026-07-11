from __future__ import annotations

from app.agents.common import clamp_score, confidence_from_score
from app.schemas.report import AgentFinding, FundamentalSnapshot


def analyze_fundamentals(snapshot: FundamentalSnapshot) -> AgentFinding:
    score = 50
    score += min(18, snapshot.profit_growth_yoy * 0.7)
    score += min(14, snapshot.roe * 0.35)
    score += min(10, snapshot.gross_margin * 0.08)
    score += min(10, snapshot.cashflow_quality * 10)
    score -= max(0, (snapshot.debt_to_asset - 45) * 0.4)
    score -= max(0, (snapshot.pe_ttm - 35) * 0.5)
    if "上修" in snapshot.forecast_revision:
        score += 5
    final_score = clamp_score(score)
    return AgentFinding(
        agent="基本面 Agent",
        conclusion="基本面质量较强" if final_score >= 70 else "基本面中性",
        score=final_score,
        confidence=confidence_from_score(final_score),
        evidence=[
            f"利润同比增长 {snapshot.profit_growth_yoy:.1f}%",
            f"ROE {snapshot.roe:.1f}%，毛利率 {snapshot.gross_margin:.1f}%",
            f"PE(TTM) {snapshot.pe_ttm:.1f}，PB {snapshot.pb:.1f}",
            f"业绩预期变化：{snapshot.forecast_revision}",
        ],
        risks=["估值不低，若盈利增速放缓会压缩安全边际。"] if snapshot.pe_ttm > 25 else [],
        counterpoints=["财务快照需要结合完整财报与行业周期复核。"],
        source_ids=["fund-001"],
    )

