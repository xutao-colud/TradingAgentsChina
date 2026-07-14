from __future__ import annotations

from app.agents.common import clamp_score, confidence_from_score
from app.config.runtime import load_runtime_settings
from app.indicators.fundamental import analyze_fundamental_quality
from app.schemas.report import AgentFinding, FundamentalSnapshot


def analyze_fundamentals(snapshot: FundamentalSnapshot) -> AgentFinding:
    config = load_runtime_settings().get("scoring", "fundamental")
    score = load_runtime_settings().get("scoring", "score_bounds", "neutral")
    score += min(config["profit_cap"], snapshot.profit_growth_yoy * config["profit_weight"])
    score += min(config["roe_cap"], snapshot.roe * config["roe_weight"])
    score += min(config["margin_cap"], snapshot.gross_margin * config["margin_weight"])
    score += min(config["cashflow_cap"], snapshot.cashflow_quality * config["cashflow_weight"])
    score -= max(0, (snapshot.debt_to_asset - config["debt_threshold"]) * config["debt_weight"])
    score -= max(0, (snapshot.pe_ttm - config["pe_threshold"]) * config["pe_weight"])
    if "上修" in snapshot.forecast_revision:
        score += config["forecast_upgrade_bonus"]
    final_score = clamp_score(score)
    quality = analyze_fundamental_quality(snapshot)
    evidence = [
        f"利润同比增长 {snapshot.profit_growth_yoy:.1f}%",
        f"ROE {snapshot.roe:.1f}%，毛利率 {snapshot.gross_margin:.1f}%",
        f"PE(TTM) {snapshot.pe_ttm:.1f}，PB {snapshot.pb:.1f}",
        f"业绩预期变化：{snapshot.forecast_revision}",
    ]
    if quality.dupont_roe is not None:
        evidence.append(f"杜邦拆解：净利率 {quality.dupont_margin:.2%} × 资产周转 {quality.asset_turnover:.2f} × 权益乘数 {quality.equity_multiplier:.2f} = ROE {quality.dupont_roe:.2%}。")
    if quality.cash_conversion is not None:
        evidence.append(f"经营现金流/净利润：{quality.cash_conversion:.2f}。")
    evidence.extend(quality.working_capital_flags)
    evidence.extend(f"同业中位数差异 {metric}: {delta:+.2f}" for metric, delta in quality.peer_comparison.items())
    if snapshot.peer_medians:
        evidence.append(
            f"同行基准报告期 {snapshot.peer_as_of or '未知'}；"
            + "，".join(
                f"{metric} 样本 {snapshot.peer_sample_sizes.get(metric, 0)} 个"
                for metric in snapshot.peer_medians
            )
        )
    return AgentFinding(
        agent="基本面 Agent",
        conclusion="基本面质量较强" if final_score >= config["strong_threshold"] else "基本面中性",
        score=final_score,
        confidence=confidence_from_score(final_score),
        evidence=evidence,
        risks=(["估值不低，若盈利增速放缓会压缩安全边际。"] if snapshot.pe_ttm > config["valuation_risk_pe"] else ["财务快照不覆盖完整财报附注、行业周期和一次性损益。"]) + quality.unavailable_reasons,
        counterpoints=["财务快照需要结合完整财报与行业周期复核。"],
        invalidation_conditions=["利润增速、ROE 或经营现金流出现连续恶化。", "业绩预期由上修转为下修且缺乏新的经营证据。"],
        source_ids=["fund-001", *([snapshot.peer_source_id] if snapshot.peer_source_id else [])],
    )
