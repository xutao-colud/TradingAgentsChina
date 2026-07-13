from __future__ import annotations

from app.config.runtime import load_runtime_settings
from app.schemas.report import AhPremiumSnapshot, DataQualityReport, SkillInsight
from app.skills.common import clamp_score


def analyze_ah_premium(
    snapshot: AhPremiumSnapshot,
    quality_reports: list[DataQualityReport],
) -> SkillInsight:
    quality = next((item for item in quality_reports if item.dataset == "ah_premium"), None)
    if snapshot.data_status != "verified":
        return _unavailable(snapshot, snapshot.unavailable_reasons or ["该股票没有可用的同日 AH 比价记录。"])
    if quality is None or quality.status != "passed":
        return _unavailable(snapshot, ["AH 比价语义质量未通过，不进入估值比较。"])
    if snapshot.ah_premium_pct is None or not snapshot.source_id:
        return _unavailable(snapshot, ["AH 溢价或来源标识缺失。"])

    config = load_runtime_settings().get("scoring", "committee_signals", "ah_premium")
    premium = float(snapshot.ah_premium_pct)
    scaled = (premium - float(config["neutral_premium_pct"])) / max(1.0, float(config["premium_scale_pct"]))
    score = clamp_score(float(config["neutral_score"]) - scaled * float(config["score_span"]))
    stage = "A股高溢价" if premium > 0 else "A股折价" if premium < 0 else "AH接近平价"
    return SkillInsight(
        skill="AH股溢价观察",
        category="valuation",
        stage=stage,
        score=score,
        conclusion=f"同日官方 AH 比价显示{stage}，溢价 {premium:.2f}%。",
        strategy="只作为跨市场相对估值证据，不单独形成交易结论。",
        evidence=[
            f"A股 {snapshot.a_symbol} 收盘 {snapshot.a_close}",
            f"H股 {snapshot.h_symbol} 收盘 {snapshot.h_close}",
            f"A/H 比价 {snapshot.ah_comparison}，溢价 {premium:.2f}%",
            f"数据时间：{snapshot.trade_date}",
        ],
        risks=[
            "A/H 股的币种、流动性、投资者结构和股东权利可能不同，溢价不等于错误定价。",
            "该指标不能替代公司基本面、汇率和跨市场交易约束分析。",
        ],
        details={
            "mode": "ah_premium",
            "admitted": True,
            "premium_pct": premium,
            "ah_comparison": snapshot.ah_comparison,
            "a_symbol": snapshot.a_symbol,
            "h_symbol": snapshot.h_symbol,
            "source_ids": [snapshot.source_id],
            "as_of": snapshot.trade_date,
        },
    )


def _unavailable(snapshot: AhPremiumSnapshot, reasons: list[str]) -> SkillInsight:
    return SkillInsight(
        skill="AH股溢价观察",
        category="valuation",
        stage="不适用" if snapshot.data_status == "not_applicable" else "数据不足",
        score=load_runtime_settings().get("scoring", "data_readiness", "insufficient_score"),
        conclusion="没有可核验的同日 AH 比价，不能生成溢价判断。",
        strategy="该维度不参与计分，继续使用其他已核验的估值证据。",
        evidence=[f"A股代码：{snapshot.a_symbol}", f"目标日期：{snapshot.trade_date}"],
        risks=list(reasons),
        details={"mode": "ah_premium", "admitted": False, "source_ids": [], "as_of": snapshot.trade_date},
    )
