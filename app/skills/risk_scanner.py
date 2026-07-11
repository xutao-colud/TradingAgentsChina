from __future__ import annotations

from app.schemas.report import FundamentalSnapshot, SkillInsight, StockProfile
from app.skills.common import clamp_score


def scan_a_share_risks(profile: StockProfile, fundamentals: FundamentalSnapshot, invalid_conditions: list[str]) -> SkillInsight:
    risk_points: list[str] = []
    score = 82
    if profile.is_st:
        score -= 25
        risk_points.append("ST/*ST 风险标识")
    if profile.is_suspended:
        score -= 35
        risk_points.append("停牌状态")
    if fundamentals.profit_growth_yoy < 0:
        score -= 14
        risk_points.append("利润同比下滑")
    if fundamentals.debt_to_asset > 60:
        score -= 12
        risk_points.append("资产负债率偏高")
    if fundamentals.pe_ttm > 45:
        score -= 10
        risk_points.append("估值偏高")
    if fundamentals.cashflow_quality < 0.6:
        score -= 12
        risk_points.append("现金流质量偏弱")
    risk_points.extend(invalid_conditions)
    final_score = clamp_score(score - len(invalid_conditions) * 8)
    if final_score >= 75:
        stage = "A级"
    elif final_score >= 60:
        stage = "B级"
    elif final_score >= 45:
        stage = "C级"
    else:
        stage = "D级"
    return SkillInsight(
        skill="A股风险扫描器",
        category="risk",
        stage=stage,
        score=final_score,
        conclusion=f"综合风险为{stage}",
        strategy="C级以下优先做风险排除，不提升结论等级。",
        evidence=[
            f"ST标识：{profile.is_st}",
            f"停牌：{profile.is_suspended}",
            f"利润增速 {fundamentals.profit_growth_yoy:.1f}%",
            f"资产负债率 {fundamentals.debt_to_asset:.1f}%",
            f"PE(TTM) {fundamentals.pe_ttm:.1f}",
        ],
        risks=risk_points,
    )

