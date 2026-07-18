from __future__ import annotations

from app.agents.common import clamp_score, confidence_from_score
from app.config.runtime import load_runtime_settings
from app.indicators.fundamental import analyze_fundamental_quality
from app.schemas.report import AgentFinding, FundamentalSnapshot


def analyze_fundamentals(snapshot: FundamentalSnapshot) -> AgentFinding:
    settings = load_runtime_settings()
    config = settings.get("scoring", "fundamental")
    score = settings.get("scoring", "score_bounds", "neutral")
    available_metrics = {
        "profit_growth_yoy": snapshot.profit_growth_yoy,
        "roe": snapshot.roe,
        "gross_margin": snapshot.gross_margin,
        "cashflow_quality": snapshot.cashflow_quality,
        "debt_to_asset": snapshot.debt_to_asset,
        "pe_ttm": snapshot.pe_ttm,
    }
    if snapshot.profit_growth_yoy is not None:
        score += min(config["profit_cap"], snapshot.profit_growth_yoy * config["profit_weight"])
    if snapshot.roe is not None:
        score += min(config["roe_cap"], snapshot.roe * config["roe_weight"])
    if snapshot.gross_margin is not None:
        score += min(config["margin_cap"], snapshot.gross_margin * config["margin_weight"])
    if snapshot.cashflow_quality is not None:
        score += min(config["cashflow_cap"], snapshot.cashflow_quality * config["cashflow_weight"])
    if snapshot.debt_to_asset is not None:
        score -= max(0, (snapshot.debt_to_asset - config["debt_threshold"]) * config["debt_weight"])
    if snapshot.pe_ttm is not None:
        score -= max(0, (snapshot.pe_ttm - config["pe_threshold"]) * config["pe_weight"])
    if "上修" in snapshot.forecast_revision:
        score += config["forecast_upgrade_bonus"]
    final_score = clamp_score(score)
    quality = analyze_fundamental_quality(snapshot)
    evidence = [f"业绩预期变化：{snapshot.forecast_revision}"]
    if snapshot.profit_growth_yoy is not None:
        evidence.append(f"利润同比增长 {snapshot.profit_growth_yoy:.1f}%")
    if snapshot.roe is not None or snapshot.gross_margin is not None:
        evidence.append(f"ROE {_display(snapshot.roe)}，毛利率 {_display(snapshot.gross_margin)}")
    if snapshot.pe_ttm is not None or snapshot.pb is not None:
        evidence.append(f"PE(TTM) {_display(snapshot.pe_ttm)}，PB {_display(snapshot.pb)}")
    missing_metrics = [name for name, value in available_metrics.items() if value is None]
    if missing_metrics:
        evidence.append(f"未取得字段：{', '.join(missing_metrics)}；缺失值未按 0 或中性事实参与计算。")
    if quality.dupont_roe is not None:
        evidence.append(f"杜邦拆解：净利率 {quality.dupont_margin:.2%} × 资产周转 {quality.asset_turnover:.2f} × 权益乘数 {quality.equity_multiplier:.2f} = ROE {quality.dupont_roe:.2%}。")
    if quality.cash_conversion is not None:
        evidence.append(f"经营现金流/净利润：{quality.cash_conversion:.2f}。")
    if snapshot.deducted_net_income is not None:
        evidence.append(
            f"扣非净利润：{_display_amount(snapshot.deducted_net_income, settings)}；"
            f"报告期：{snapshot.statement_as_of or '未知'}。"
        )
    if quality.non_recurring_profit_ratio is not None:
        evidence.append(
            f"归母净利润与扣非净利润差额占归母净利润 {quality.non_recurring_profit_ratio:+.1f}%"
            f"（差额 {_display_amount(quality.non_recurring_profit_impact, settings, signed=True)}）。"
        )
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
    scope_risks = list(snapshot.scope_limitations) or [
        "财务数据源未声明是否覆盖完整财报附注；异常项目和会计口径仍需核验原文。",
        "行业周期需由行业景气度数据独立验证，不能从单公司财务快照推断。",
    ]
    non_recurring_threshold = float(settings.get("domain_knowledge", "financial_quality", "non_recurring_warning_pct"))
    if (
        quality.non_recurring_profit_ratio is not None
        and abs(quality.non_recurring_profit_ratio) >= non_recurring_threshold
    ):
        scope_risks.append(
            f"归母与扣非净利润差额占比 {quality.non_recurring_profit_ratio:+.1f}%，一次性损益影响较大，需核验项目明细。"
        )
    risks = (
        ["估值不低，若盈利增速放缓会压缩安全边际。"]
        if snapshot.pe_ttm is not None and snapshot.pe_ttm > config["valuation_risk_pe"]
        else []
    ) + scope_risks + quality.unavailable_reasons
    risks = list(dict.fromkeys(risks))
    return AgentFinding(
        agent="基本面 Agent",
        conclusion=("基本面数据不足" if len(missing_metrics) == len(available_metrics) else "基本面质量较强" if final_score >= config["strong_threshold"] else "基本面中性"),
        score=final_score,
        confidence=0.0 if len(missing_metrics) == len(available_metrics) else confidence_from_score(final_score),
        evidence=evidence,
        risks=risks,
        counterpoints=["结构化财务快照只支持已取得字段的拆解；财报附注、行业周期及异常损益明细仍可能推翻当前解释。"],
        invalidation_conditions=["利润增速、ROE 或经营现金流出现连续恶化。", "业绩预期由上修转为下修且缺乏新的经营证据。"],
        source_ids=(["fund-001"] if any(value is not None for value in available_metrics.values()) else []) + ([snapshot.peer_source_id] if snapshot.peer_source_id else []),
    )


def _display(value: float | None) -> str:
    return "未取得" if value is None else f"{value:.1f}"


def _display_amount(value: float, settings, *, signed: bool = False) -> str:
    config = settings.get("domain_knowledge", "financial_quality")
    scaled = value / float(config["amount_display_divisor"])
    formatted = f"{scaled:+.2f}" if signed else f"{scaled:.2f}"
    return formatted + str(config["amount_display_unit"])
