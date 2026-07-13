from __future__ import annotations

from app.config.runtime import load_runtime_settings
from app.schemas.report import (
    DataQualityReport,
    FundamentalSnapshot,
    IndustryContext,
    IndustryFlowObservation,
    SkillInsight,
)
from app.skills.common import clamp_score


def analyze_industry_prosperity(
    context: IndustryContext,
    fundamentals: FundamentalSnapshot,
    quality_reports: list[DataQualityReport] | None = None,
) -> SkillInsight:
    """Assess industry-wide evidence without turning theme matches into facts."""
    config = load_runtime_settings().get("domain_knowledge", "industry_prosperity")
    reports = {item.dataset: item for item in list(quality_reports or []) if item.provider == "tushare"}
    flow_quality = reports.get("industry_flow")
    valuation_quality = reports.get("industry_valuation")
    valuation_quality = reports.get("industry_valuation")
    target_flow = _find_flow(context.flow_observations, context.industry)
    flow_is_admissible = (
        target_flow is not None
        and len(context.flow_observations) >= int(config["minimum_flow_universe"])
        and (flow_quality is None or flow_quality.status == "passed")
    )
    if not flow_is_admissible:
        reasons = [*context.unavailable_reasons]
        if target_flow is None:
            reasons.append(f"未取得 {context.industry} 的同日行业资金记录。")
        if flow_quality is not None and flow_quality.status != "passed":
            reasons.extend(item.message for item in flow_quality.issues)
        return SkillInsight(
            skill="行业景气度分析",
            category="industry",
            stage="证据不足",
            score=load_runtime_settings().get("scoring", "data_readiness", "insufficient_score"),
            conclusion="行业分类或全行业资金横截面未通过质量审查，不能形成行业景气判断。",
            strategy="保留个股和题材研究，但暂停把行业排名、估值分位或产业链传导用于委员会计分。",
            evidence=[f"目标行业：{context.industry}", f"数据时间：{context.as_of}"],
            risks=_unique(reasons) or ["行业数据不可用。"],
            details={
                "admissible": False,
                "as_of": context.as_of,
                "source_ids": list(context.source_ids),
                "counter_evidence": ["缺少可比行业横截面，任何行业强弱结论都可能是个股噪音。"],
                "invalidation_conditions": ["行业分类、观察日期或来源质量不满足要求。"],
            },
        )

    ordered_flows = sorted(context.flow_observations, key=lambda item: item.net_amount, reverse=True)
    flow_rank = next(index for index, item in enumerate(ordered_flows, start=1) if item is target_flow)
    flow_percentile = _rank_percentile(flow_rank, len(ordered_flows))
    flow_impact = (flow_percentile - 50) / 50 * float(config["flow_percentile_weight"])

    valuation = _valuation_metrics(context, int(config["minimum_valuation_history"]))
    if valuation_quality is not None and valuation_quality.status != "passed":
        valuation["available"] = False
        valuation["quality_status"] = valuation_quality.status
    if valuation_quality is not None and valuation_quality.status != "passed":
        valuation["available"] = False
        valuation["quality_status"] = valuation_quality.status
    valuation_impact = 0.0
    if valuation["available"]:
        valuation_percentiles = [
            value
            for value in (valuation["pe_percentile"], valuation["pb_percentile"])
            if isinstance(value, (int, float))
        ]
        valuation_level = sum(valuation_percentiles) / len(valuation_percentiles)
        valuation_impact = (50 - valuation_level) / 50 * float(config["valuation_percentile_weight"])

    growth = _growth_metrics(fundamentals)
    growth_gaps = [
        value for value in (growth["revenue_gap_pct"], growth["profit_gap_pct"])
        if isinstance(value, (int, float))
    ]
    growth_impact = 0.0
    if growth_gaps:
        mean_gap = sum(growth_gaps) / len(growth_gaps)
        growth_impact = max(
            -float(config["growth_gap_max_impact"]),
            min(
                float(config["growth_gap_max_impact"]),
                mean_gap / float(config["growth_gap_scale_pct"]) * float(config["growth_gap_max_impact"]),
            ),
        )

    chain = _chain_metrics(context, int(config["minimum_chain_stages"]))
    chain_impact = 0.0
    if chain["available"] and chain["direction"] == "positive":
        chain_impact = float(config["chain_alignment_impact"])
    elif chain["available"] and chain["direction"] == "negative":
        chain_impact = -float(config["chain_alignment_impact"])

    score = clamp_score(
        float(config["neutral_score"])
        + flow_impact
        + valuation_impact
        + growth_impact
        + chain_impact
    )
    stage = "景气证据偏强" if score >= config["strong_score"] else "景气证据偏弱" if score <= config["weak_score"] else "景气分化"

    evidence = [
        f"{context.as_of} {context.industry} 行业资金净额 {target_flow.net_amount:.0f} 元，排名 {flow_rank}/{len(ordered_flows)}",
        f"行业资金横截面百分位 {flow_percentile:.1f}",
    ]
    if valuation["available"]:
        evidence.append(
            f"行业估值历史分位：PE {valuation['pe_percentile'] if valuation['pe_percentile'] is not None else '缺失'}，"
            f"PB {valuation['pb_percentile'] if valuation['pb_percentile'] is not None else '缺失'}"
        )
    if growth_gaps:
        evidence.append(
            f"个股相对行业增速差：营收 {growth['revenue_gap_pct'] if growth['revenue_gap_pct'] is not None else '缺失'} 个百分点，"
            f"利润 {growth['profit_gap_pct'] if growth['profit_gap_pct'] is not None else '缺失'} 个百分点"
        )
    if chain["available"]:
        evidence.append(f"产业链资金传导：{chain['direction']}，覆盖 {chain['matched_nodes']}/{chain['total_nodes']} 个节点")

    counter_evidence: list[str] = []
    if target_flow.net_amount > 0 and growth_gaps and sum(growth_gaps) / len(growth_gaps) < 0:
        counter_evidence.append("行业资金流入，但个股盈利增速落后行业，资金强不等于公司受益。")
    if target_flow.net_amount < 0 and growth_gaps and sum(growth_gaps) / len(growth_gaps) > 0:
        counter_evidence.append("个股盈利增速领先行业，但行业资金净流出，短期估值扩张缺少横截面配合。")
    if chain["available"] and chain["direction"] == "mixed":
        counter_evidence.append("上下游资金方向分化，暂未形成完整景气传导。")

    risks = list(context.unavailable_reasons)
    if not valuation["available"]:
        risks.append("行业估值历史样本不足，PE/PB 分位未参与评分。")
    if not growth_gaps:
        risks.append("缺少同报告期行业增速中位数，无法判断个股是否跑赢行业。")
    if not chain["available"]:
        risks.append("产业链节点或节点资金记录不足，未把产业链传导计入评分。")
    risks.append("行业资金流是观察性证据，不能证明机构身份、因果关系或未来收益。")

    admitted_source_ids = list(context.source_ids)
    if growth_gaps and fundamentals.peer_source_id:
        admitted_source_ids.append(fundamentals.peer_source_id)
    return SkillInsight(
        skill="行业景气度分析",
        category="industry",
        stage=stage,
        score=score,
        conclusion=f"当前可核验证据显示 {context.industry} 处于{stage}状态。",
        strategy="把行业景气作为战法适配和质证条件；仍需由公司财务、市场状态与风险条件共同确认。",
        evidence=evidence,
        risks=_unique(risks),
        details={
            "admissible": True,
            "as_of": context.as_of,
            "source_ids": _unique(admitted_source_ids),
            "flow": {
                "net_amount": target_flow.net_amount,
                "rank": flow_rank,
                "total": len(ordered_flows),
                "percentile": round(flow_percentile, 2),
            },
            "valuation": valuation,
            "growth": growth,
            "chain": chain,
            "score_components": {
                "base": config["neutral_score"],
                "flow": round(flow_impact, 2),
                "valuation": round(valuation_impact, 2),
                "growth": round(growth_impact, 2),
                "chain": round(chain_impact, 2),
            },
            "counter_evidence": counter_evidence or ["尚无足以推翻当前行业判断的结构化反证，但缺项仍保留为风险。"],
            "invalidation_conditions": [
                "行业资金排名反转或数据日期不再与分析日对齐。",
                "后续财报使个股与行业盈利增速差方向反转。",
                "产业链相邻环节由同向转为明显分化。",
            ],
        },
    )


def _find_flow(items: list[IndustryFlowObservation], industry: str) -> IndustryFlowObservation | None:
    normalized = "".join(industry.split()).casefold()
    return next((item for item in items if "".join(item.industry.split()).casefold() == normalized), None)


def _rank_percentile(rank: int, total: int) -> float:
    return 50.0 if total <= 1 else (total - rank) / (total - 1) * 100


def _percentile_rank(values: list[float], current: float) -> float:
    return round(sum(value <= current for value in values) / len(values) * 100, 2)


def _valuation_metrics(context: IndustryContext, minimum_history: int) -> dict[str, object]:
    ordered = sorted(context.valuation_history, key=lambda item: item.trade_date)
    pe_values = [float(item.pe_ttm_median) for item in ordered if item.pe_ttm_median is not None]
    pb_values = [float(item.pb_median) for item in ordered if item.pb_median is not None]
    latest = ordered[-1] if ordered else None
    available = bool(
        latest
        and max(len(pe_values), len(pb_values)) >= minimum_history
        and (latest.pe_ttm_median is not None or latest.pb_median is not None)
    )
    return {
        "available": available,
        "as_of": latest.trade_date if latest else None,
        "history_points": len(ordered),
        "current_pe_ttm": latest.pe_ttm_median if latest else None,
        "current_pb": latest.pb_median if latest else None,
        "pe_percentile": _percentile_rank(pe_values, float(latest.pe_ttm_median)) if available and latest and latest.pe_ttm_median is not None and pe_values else None,
        "pb_percentile": _percentile_rank(pb_values, float(latest.pb_median)) if available and latest and latest.pb_median is not None and pb_values else None,
    }


def _growth_metrics(fundamentals: FundamentalSnapshot) -> dict[str, float | str | None]:
    industry_revenue = fundamentals.peer_medians.get("revenue_growth_yoy")
    industry_profit = fundamentals.peer_medians.get("profit_growth_yoy")
    return {
        "peer_as_of": fundamentals.peer_as_of,
        "source_id": fundamentals.peer_source_id,
        "company_revenue_growth_yoy": fundamentals.revenue_growth_yoy,
        "industry_revenue_growth_yoy": industry_revenue,
        "revenue_gap_pct": round(fundamentals.revenue_growth_yoy - industry_revenue, 2) if industry_revenue is not None else None,
        "company_profit_growth_yoy": fundamentals.profit_growth_yoy,
        "industry_profit_growth_yoy": industry_profit,
        "profit_gap_pct": round(fundamentals.profit_growth_yoy - industry_profit, 2) if industry_profit is not None else None,
    }


def _chain_metrics(context: IndustryContext, minimum_stages: int) -> dict[str, object]:
    matched: list[tuple[str, str, float]] = []
    for node in context.chain_nodes:
        flow = _find_flow(context.flow_observations, node.industry)
        if flow is not None:
            matched.append((node.stage, node.industry, flow.net_amount))
    stages = {stage for stage, _, _ in matched}
    available = len(stages) >= minimum_stages
    values = [value for _, _, value in matched]
    direction = "insufficient"
    if available and values and all(value > 0 for value in values):
        direction = "positive"
    elif available and values and all(value < 0 for value in values):
        direction = "negative"
    elif available:
        direction = "mixed"
    return {
        "available": available,
        "direction": direction,
        "matched_nodes": len(matched),
        "total_nodes": len(context.chain_nodes),
        "stages": [
            {"stage": stage, "industry": industry, "net_amount": amount}
            for stage, industry, amount in matched
        ],
    }


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))
