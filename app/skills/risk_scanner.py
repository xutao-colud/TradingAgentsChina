from __future__ import annotations

from app.schemas.report import FundamentalSnapshot, SkillInsight, StockProfile
from app.skills.common import clamp_score


def scan_a_share_risks(profile: StockProfile, fundamentals: FundamentalSnapshot, invalid_conditions: list[str]) -> SkillInsight:
    risk_points: list[str] = []
    deductions: list[dict[str, object]] = []
    score = 82
    if profile.is_st:
        score -= 25
        risk_points.append("ST/*ST 风险标识")
        deductions.append(_deduction("ST/*ST", 25, "交易属性风险", "存在 ST/*ST 标识，需优先排除退市、经营异常和流动性折价。"))
    if profile.is_suspended:
        score -= 35
        risk_points.append("停牌状态")
        deductions.append(_deduction("停牌", 35, "交易可执行风险", "股票处于停牌状态，无法按常规短线/波段计划执行。"))
    if fundamentals.profit_growth_yoy < 0:
        score -= 14
        risk_points.append("利润同比下滑")
        deductions.append(_deduction("利润增速", 14, "基本面风险", "利润同比为负，说明盈利动能走弱，趋势信号需要更强资金和公告验证。"))
    if fundamentals.debt_to_asset > 60:
        score -= 12
        risk_points.append("资产负债率偏高")
        deductions.append(_deduction("资产负债率", 12, "资产负债风险", "资产负债率高于 60%，财务弹性下降，遇到行业下行时回撤可能放大。"))
    if fundamentals.pe_ttm > 45:
        score -= 10
        risk_points.append("估值偏高")
        deductions.append(_deduction("估值", 10, "估值风险", "PE(TTM) 高于 45 倍，若业绩或题材兑现不及预期，估值回落压力更大。"))
    if fundamentals.cashflow_quality < 0.6:
        score -= 12
        risk_points.append("现金流质量偏弱")
        deductions.append(_deduction("现金流质量", 12, "盈利质量风险", "现金流质量低于 0.60，利润含金量不足，需核验应收、存货和经营现金流。"))
    for condition in invalid_conditions:
        risk_points.append(condition)
        deductions.append(_deduction("交易规则/流动性", 8, "A股规则风险", condition))
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
        strategy=_stage_strategy(stage),
        evidence=[
            f"ST标识：{profile.is_st}",
            f"停牌：{profile.is_suspended}",
            f"利润增速 {fundamentals.profit_growth_yoy:.1f}%",
            f"资产负债率 {fundamentals.debt_to_asset:.1f}%",
            f"PE(TTM) {fundamentals.pe_ttm:.1f}",
            f"现金流质量 {fundamentals.cashflow_quality:.2f}",
        ],
        risks=risk_points,
        details={
            "mode": "risk_scan",
            "grade": stage,
            "score": final_score,
            "base_score": 82,
            "grade_explanation": _grade_explanation(stage),
            "grade_guide": _grade_guide(),
            "deductions": deductions,
            "checks": _risk_checks(profile, fundamentals, invalid_conditions),
            "next_checks": _next_checks(stage, risk_points),
            "principle": "风险扫描器不是预测涨跌，而是先判断这只股票是否允许进入下一层策略讨论；风险等级越低，越需要先做排除题，而不是提高买入结论。",
        },
    )


def _deduction(item: str, points: int, category: str, reason: str) -> dict[str, object]:
    return {"item": item, "points": points, "category": category, "reason": reason}


def _risk_checks(profile: StockProfile, fundamentals: FundamentalSnapshot, invalid_conditions: list[str]) -> list[dict[str, object]]:
    checks = [
        _check("ST/*ST", "无 ST 标识", "通过" if not profile.is_st else "触发", profile.is_st, "ST 股存在退市、流动性和交易限制风险。"),
        _check("停牌", "正常交易", "通过" if not profile.is_suspended else "触发", profile.is_suspended, "停牌时策略无法执行，价格发现不连续。"),
        _check("利润增速", "利润同比 >= 0%", f"{fundamentals.profit_growth_yoy:.1f}%", fundamentals.profit_growth_yoy < 0, "利润下滑会削弱估值和趋势的持续性。"),
        _check("资产负债率", "资产负债率 <= 60%", f"{fundamentals.debt_to_asset:.1f}%", fundamentals.debt_to_asset > 60, "高杠杆公司在下行周期更容易出现现金流压力。"),
        _check("估值", "PE(TTM) <= 45", f"{fundamentals.pe_ttm:.1f}", fundamentals.pe_ttm > 45, "高估值必须有更强业绩或产业逻辑支撑。"),
        _check("现金流质量", "经营现金流质量 >= 0.60", f"{fundamentals.cashflow_quality:.2f}", fundamentals.cashflow_quality < 0.6, "现金流偏弱说明利润兑现质量需要复核。"),
    ]
    for condition in invalid_conditions:
        checks.append(_check("规则/流动性", "无交易规则降级项", condition, True, "A股交易制度和流动性约束会直接影响策略可执行性。"))
    return checks


def _check(name: str, threshold: str, observed: object, triggered: bool, explanation: str) -> dict[str, object]:
    return {
        "name": name,
        "threshold": threshold,
        "observed": observed,
        "status": "风险触发" if triggered else "通过",
        "severity": "warning" if triggered else "ok",
        "explanation": explanation,
    }


def _grade_guide() -> list[dict[str, str]]:
    return [
        {"grade": "A级", "range": "75-100", "meaning": "风险相对可控，可以进入策略比较，但仍需看资金和价格位置。"},
        {"grade": "B级", "range": "60-74", "meaning": "存在可解释风险，需要逐项复核；可以观察，但不宜因为单项强势直接升结论。"},
        {"grade": "C级", "range": "45-59", "meaning": "风险偏高，先做排除题；除非有强证据修复，否则降低仓位和置信度。"},
        {"grade": "D级", "range": "0-44", "meaning": "重大风险区，优先规避；不进入进攻型策略讨论。"},
    ]


def _grade_explanation(stage: str) -> str:
    mapping = {
        "A级": "当前没有触发主要硬风险，风险扫描允许进入下一层策略比较。",
        "B级": "当前有中等风险项，风险尚未到否决级别，但需要核验财务质量、公告和流动性。",
        "C级": "当前风险项已经影响策略可靠性，应先排除风险，再讨论入场条件。",
        "D级": "当前存在重大风险或多项风险叠加，不适合形成进攻型结论。",
    }
    return mapping.get(stage, "风险等级未知，需要复核数据完整性。")


def _stage_strategy(stage: str) -> str:
    if stage == "A级":
        return "风险扫描允许进入策略比较，但仍需由资金、趋势和公告继续验证。"
    if stage == "B级":
        return "B级可继续研究，但要先解释扣分项；不能只因趋势或题材强就提高结论等级。"
    if stage == "C级":
        return "C级优先做风险排除，不提升结论等级，等待风险项改善。"
    return "D级优先规避，不进入进攻型交易计划。"


def _next_checks(stage: str, risk_points: list[str]) -> list[str]:
    checks = [
        "核验最近一期公告和问询/处罚记录，确认是否存在未反映的硬风险。",
        "复核经营现金流、应收账款、存货和商誉，判断利润质量。",
        "结合成交额、换手率和跌停/涨停制度，确认短线可执行性。",
    ]
    if risk_points:
        checks.insert(0, f"优先解释已触发风险：{'、'.join(risk_points[:3])}。")
    if stage in {"C级", "D级"}:
        checks.append("风险项未解除前，只允许观察或模拟，不提高仓位假设。")
    return checks
