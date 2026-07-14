from __future__ import annotations

from statistics import mean
from typing import Any

from app.config.runtime import load_runtime_settings
from app.schemas.report import DailyPrice, EvidenceSource, FundamentalSnapshot, SkillInsight, StockProfile


def scan_a_share_risks(
    profile: StockProfile,
    fundamentals: FundamentalSnapshot,
    invalid_conditions: list[str],
    *,
    prices: list[DailyPrice] | None = None,
    evidence_sources: list[EvidenceSource] | None = None,
) -> SkillInsight:
    """Deterministic, configuration-driven A-share risk exclusion scan."""

    settings = load_runtime_settings()
    config = settings.get("domain_knowledge", "risk_scanner")
    thresholds = config["thresholds"]
    deductions_config = config["deductions"]
    liquidity_rules = settings.get("market_rules", "liquidity")
    source_by_id = {item.id: item for item in (evidence_sources or [])}
    checks: list[dict[str, Any]] = []
    risk_points: list[str] = []
    deductions: list[dict[str, object]] = []

    def add_check(
        *,
        name: str,
        threshold: str,
        observed: object,
        triggered: bool | None,
        deduction_key: str | None,
        category: str,
        risk: str,
        counterpoint: str,
        invalidation: str,
        source_ids: list[str],
        source_time: str | None,
        deduction_override: int | None = None,
    ) -> None:
        points = (
            deduction_override
            if deduction_override is not None
            else int(deductions_config[deduction_key]) if deduction_key is not None else 0
        )
        status = "数据不足" if triggered is None else "风险触发" if triggered else "通过"
        checks.append({
            "name": name,
            "threshold": threshold,
            "observed": observed,
            "status": status,
            "severity": "unknown" if triggered is None else "warning" if triggered else "ok",
            "deduction": points if triggered else 0,
            "source_ids": source_ids,
            "source_time": source_time,
            "counterpoint": counterpoint,
            "risk": risk,
            "invalidation_condition": invalidation,
        })
        if triggered:
            risk_points.append(risk)
            deductions.append(_deduction(name, points, category, risk, source_ids, source_time))

    profile_traceable = "profile-001" in source_by_id
    add_check(
        name="ST/*ST",
        threshold="无 ST/*ST 标识",
        observed=profile.is_st,
        triggered=profile.is_st if profile_traceable else None,
        deduction_key="st",
        category="交易属性风险",
        risk="存在 ST/*ST 标识",
        counterpoint="ST 标识本身不等同于立即退市，但会改变涨跌停、流动性和风险约束。",
        invalidation="证券简称及交易状态恢复为非 ST，且来源完成更新。",
        source_ids=_available_ids(["profile-001"], source_by_id),
        source_time=_source_time(["profile-001"], source_by_id),
    )
    add_check(
        name="停牌",
        threshold="处于正常交易状态",
        observed=profile.is_suspended,
        triggered=profile.is_suspended if profile_traceable else None,
        deduction_key="suspended",
        category="交易可执行风险",
        risk="股票处于停牌状态",
        counterpoint="停牌可能对应重组等事件，但停牌期间无法验证连续价格发现。",
        invalidation="恢复交易并形成可验证的成交与价格记录。",
        source_ids=_available_ids(["profile-001"], source_by_id),
        source_time=_source_time(["profile-001"], source_by_id),
    )
    add_check(
        name="利润增速",
        threshold=f">= {thresholds['minimum_profit_growth_yoy']}%",
        observed=fundamentals.profit_growth_yoy,
        triggered=_below(fundamentals.profit_growth_yoy, float(thresholds["minimum_profit_growth_yoy"])),
        deduction_key="profit_decline",
        category="基本面风险",
        risk="利润同比下滑",
        counterpoint="单期利润可能受非经常项目或行业季节性影响，需要结合三表与后续公告。",
        invalidation="后续点时财报确认利润增速恢复到配置阈值以上。",
        source_ids=_fundamental_source_ids(fundamentals, source_by_id),
        source_time=fundamentals.statement_as_of,
    )
    add_check(
        name="资产负债率",
        threshold=f"<= {thresholds['maximum_debt_to_asset_pct']}%",
        observed=fundamentals.debt_to_asset,
        triggered=_above(fundamentals.debt_to_asset, float(thresholds["maximum_debt_to_asset_pct"])),
        deduction_key="high_debt",
        category="资产负债风险",
        risk="资产负债率偏高",
        counterpoint="金融及重资产行业需要结合行业中位数解释，不能跨行业机械比较。",
        invalidation="后续财报确认负债率回落，或同业证据证明该水平不构成异常。",
        source_ids=_fundamental_source_ids(fundamentals, source_by_id),
        source_time=fundamentals.statement_as_of,
    )
    add_check(
        name="估值",
        threshold=f"PE(TTM) <= {thresholds['maximum_pe_ttm']}",
        observed=fundamentals.pe_ttm,
        triggered=_above(fundamentals.pe_ttm, float(thresholds["maximum_pe_ttm"])),
        deduction_key="high_valuation",
        category="估值风险",
        risk="PE(TTM) 偏高",
        counterpoint="高增长公司可获得估值溢价，但必须由可追溯盈利增速与行业景气证据支持。",
        invalidation="盈利兑现或价格变化使 PE(TTM) 回到阈值以内。",
        source_ids=_fundamental_source_ids(fundamentals, source_by_id),
        source_time=fundamentals.statement_as_of,
    )
    add_check(
        name="现金流质量",
        threshold=f">= {thresholds['minimum_cashflow_quality']}",
        observed=fundamentals.cashflow_quality,
        triggered=_below(fundamentals.cashflow_quality, float(thresholds["minimum_cashflow_quality"])),
        deduction_key="weak_cashflow",
        category="盈利质量风险",
        risk="经营现金流质量偏弱",
        counterpoint="扩产或营运资本波动可能短期压低现金流，需结合应收与存货验证。",
        invalidation="后续财报确认经营现金流质量恢复到阈值以上。",
        source_ids=_fundamental_source_ids(fundamentals, source_by_id),
        source_time=fundamentals.statement_as_of,
    )

    reduction = profile.major_shareholder_reduction
    reduction_traceable = bool(
        profile.major_shareholder_reduction_source_ids and profile.major_shareholder_reduction_as_of
    )
    add_check(
        name="重要股东减持",
        threshold=f"最近 {config['holder_reduction_lookback_days']} 日无重要股东减持披露",
        observed=profile.major_shareholder_reduction_count if reduction is not None else None,
        triggered=reduction if reduction_traceable else None,
        deduction_key="major_shareholder_reduction",
        category="股东行为风险",
        risk="回看窗口内存在重要股东减持披露",
        counterpoint="减持原因和规模可能不同，需继续核验占流通股比例与执行进度。",
        invalidation="回看窗口届满且无新增减持，或公告明确终止减持计划。",
        source_ids=profile.major_shareholder_reduction_source_ids,
        source_time=profile.major_shareholder_reduction_as_of,
    )

    inquiry_count = profile.inquiry_count
    inquiry_traceable = bool(profile.inquiry_source_ids and profile.inquiry_as_of)
    inquiry_points = min(
        int(inquiry_count or 0) * int(deductions_config["inquiry_each"]),
        int(deductions_config["inquiry_maximum"]),
    )
    add_check(
        name="交易所问询",
        threshold=f"最近 {config['inquiry_lookback_days']} 日内收到的问询函为 0 份",
        observed=inquiry_count,
        triggered=None if inquiry_count is None or not inquiry_traceable else inquiry_count > 0,
        deduction_key=None,
        deduction_override=inquiry_points,
        category="监管风险",
        risk="回看窗口内存在交易所问询函",
        counterpoint="收到问询不等于违规，回复内容、是否按期回复及市场反应决定风险是否闭环。",
        invalidation="全部问询已获可核验回复且后续未出现监管升级。",
        source_ids=profile.inquiry_source_ids,
        source_time=profile.inquiry_as_of,
    )

    goodwill_ratio = fundamentals.goodwill_ratio
    goodwill_traceable = bool(fundamentals.goodwill_source_id and fundamentals.goodwill_as_of)
    add_check(
        name="商誉占净资产",
        threshold=f"<= {thresholds['maximum_goodwill_ratio_pct']}%",
        observed=goodwill_ratio,
        triggered=None if goodwill_ratio is None or not goodwill_traceable else goodwill_ratio > float(thresholds["maximum_goodwill_ratio_pct"]),
        deduction_key="high_goodwill",
        category="商誉减值风险",
        risk="商誉占净资产比例偏高",
        counterpoint="高商誉不必然减值，但并购标的业绩下滑时会放大净资产与利润波动。",
        invalidation="审计财报确认商誉下降，或净资产增长使比例回落至阈值以内。",
        source_ids=[fundamentals.goodwill_source_id] if fundamentals.goodwill_source_id else [],
        source_time=fundamentals.goodwill_as_of,
    )

    pledge_ratio = fundamentals.pledge_ratio
    pledge_traceable = bool(fundamentals.pledge_source_id and fundamentals.pledge_as_of)
    add_check(
        name="股权质押比例",
        threshold=f"<= {thresholds['maximum_pledge_ratio_pct']}%",
        observed=pledge_ratio,
        triggered=None if pledge_ratio is None or not pledge_traceable else pledge_ratio > float(thresholds["maximum_pledge_ratio_pct"]),
        deduction_key="high_pledge",
        category="股权质押风险",
        risk="股权质押比例偏高",
        counterpoint="质押比例需结合股价安全边际、质权人及补充担保能力判断。",
        invalidation="最新质押统计确认比例回落至阈值以内。",
        source_ids=[fundamentals.pledge_source_id] if fundamentals.pledge_source_id else [],
        source_time=fundamentals.pledge_as_of,
    )

    recent_prices = list((prices or [])[-int(config["liquidity_window_days"]):])
    minimum_observations = int(config["minimum_liquidity_observations"])
    amount_values = [item.amount for item in recent_prices]
    liquidity_source_ids = _available_ids(["price-001"], source_by_id)
    average_amount = (
        mean(amount_values)
        if len(amount_values) >= minimum_observations and liquidity_source_ids
        else None
    )
    liquidity_as_of = recent_prices[-1].trade_date if recent_prices else None
    low_amount = None if average_amount is None else average_amount < float(liquidity_rules["minimum_amount"])
    add_check(
        name="日均成交额",
        threshold=f">= {liquidity_rules['minimum_amount']}",
        observed=average_amount,
        triggered=low_amount,
        deduction_key="low_average_amount",
        category="流动性风险",
        risk="滚动日均成交额偏低",
        counterpoint="低成交额可能适用于小容量策略，但会增加冲击成本和退出不确定性。",
        invalidation="配置窗口内日均成交额恢复到最低阈值以上。",
        source_ids=liquidity_source_ids,
        source_time=liquidity_as_of,
    )
    turnover_values = [item.turnover_rate for item in recent_prices if item.turnover_rate is not None]
    average_turnover = (
        mean(turnover_values)
        if len(turnover_values) >= minimum_observations and liquidity_source_ids
        else None
    )
    low_turnover = None if average_turnover is None else average_turnover < float(liquidity_rules["minimum_turnover_rate"])
    add_check(
        name="平均换手率",
        threshold=f">= {liquidity_rules['minimum_turnover_rate']}%",
        observed=average_turnover,
        triggered=low_turnover,
        deduction_key="low_average_turnover",
        category="流动性风险",
        risk="滚动平均换手率偏低",
        counterpoint="低换手可能反映稳定持股结构，但同时降低短线价格发现与可退出性。",
        invalidation="配置窗口内平均换手率恢复到最低阈值以上。",
        source_ids=liquidity_source_ids,
        source_time=liquidity_as_of,
    )

    rolling_liquidity_triggered = bool(low_amount or low_turnover)
    markers = tuple(str(item) for item in config["liquidity_condition_markers"])
    for condition in invalid_conditions:
        if rolling_liquidity_triggered and any(marker in condition for marker in markers):
            continue
        add_check(
            name="交易规则/可执行性",
            threshold="无交易规则降级项",
            observed=condition,
            triggered=True,
            deduction_key="invalid_condition",
            category="A股规则风险",
            risk=condition,
            counterpoint="规则降级项可能随交易状态或流动性更新而解除。",
            invalidation="对应交易状态或流动性条件恢复并由新数据验证。",
            source_ids=liquidity_source_ids or _available_ids(["profile-001"], source_by_id),
            source_time=liquidity_as_of,
        )

    total_deduction = sum(int(item["points"]) for item in deductions)
    score_bounds = settings.get("scoring", "score_bounds")
    final_score = max(
        int(score_bounds["min"]),
        min(int(score_bounds["max"]), int(config["base_score"]) - total_deduction),
    )
    stage = _grade(final_score, config["grade_thresholds"])
    insufficient = [item["name"] for item in checks if item["status"] == "数据不足"]
    return SkillInsight(
        skill="A股风险扫描器",
        category="risk",
        stage=stage,
        score=final_score,
        conclusion=f"综合风险为{stage}" + (f"；{len(insufficient)} 项数据不足" if insufficient else ""),
        strategy=_stage_strategy(stage, bool(insufficient)),
        evidence=[f"{item['name']}：{item['observed']}（{item['status']}）" for item in checks],
        risks=risk_points + [f"数据不足：{name}" for name in insufficient],
        details={
            "mode": "risk_scan",
            "grade": stage,
            "score": final_score,
            "base_score": int(config["base_score"]),
            "total_deduction": total_deduction,
            "grade_explanation": _grade_explanation(stage),
            "grade_guide": _grade_guide(
                config["grade_thresholds"],
                int(score_bounds["min"]),
                int(score_bounds["max"]),
            ),
            "deductions": deductions,
            "checks": checks,
            "insufficient_checks": insufficient,
            "next_checks": _next_checks(stage, risk_points, insufficient),
            "principle": "风险扫描只做可追溯的排除与降级；缺失数据不等于无风险，也不用于推断收益或生成交易指令。",
            "rule_version": settings.rule_version,
        },
    )


def _deduction(
    item: str,
    points: int,
    category: str,
    reason: str,
    source_ids: list[str],
    source_time: str | None,
) -> dict[str, object]:
    return {
        "item": item,
        "points": points,
        "category": category,
        "reason": reason,
        "source_ids": source_ids,
        "source_time": source_time,
    }


def _available_ids(candidates: list[str], source_by_id: dict[str, EvidenceSource]) -> list[str]:
    return [source_id for source_id in candidates if source_id in source_by_id]


def _source_time(candidates: list[str], source_by_id: dict[str, EvidenceSource]) -> str | None:
    values = [source_by_id[source_id].as_of for source_id in candidates if source_id in source_by_id]
    return max(values) if values else None


def _fundamental_source_ids(
    fundamentals: FundamentalSnapshot,
    source_by_id: dict[str, EvidenceSource],
) -> list[str]:
    ids = _available_ids(["fund-001"], source_by_id)
    return ids or ([fundamentals.goodwill_source_id] if fundamentals.goodwill_source_id else [])


def _below(value: float | None, threshold: float) -> bool | None:
    return None if value is None else value < threshold


def _above(value: float | None, threshold: float) -> bool | None:
    return None if value is None else value > threshold


def _grade(score: int, thresholds: dict[str, int]) -> str:
    if score >= thresholds["A"]:
        return "A级"
    if score >= thresholds["B"]:
        return "B级"
    if score >= thresholds["C"]:
        return "C级"
    return "D级"


def _grade_guide(thresholds: dict[str, int], minimum_score: int, maximum_score: int) -> list[dict[str, str]]:
    return [
        {"grade": "A级", "range": f"{thresholds['A']}-{maximum_score}", "meaning": "主要硬风险未触发，可继续进入策略证据比较。"},
        {"grade": "B级", "range": f"{thresholds['B']}-{thresholds['A'] - 1}", "meaning": "存在可解释风险，需要逐项复核。"},
        {"grade": "C级", "range": f"{thresholds['C']}-{thresholds['B'] - 1}", "meaning": "风险偏高，应先完成风险排除。"},
        {"grade": "D级", "range": f"{minimum_score}-{thresholds['C'] - 1}", "meaning": "重大或叠加风险，不进入进攻型策略论证。"},
    ]


def _grade_explanation(stage: str) -> str:
    return {
        "A级": "当前未触发主要硬风险，但仍需保留反证和失效条件。",
        "B级": "当前存在中等风险项，需要核验财务质量、监管公告和流动性。",
        "C级": "当前风险项已经影响策略可靠性，应先排除风险。",
        "D级": "当前存在重大或多项叠加风险，不适合形成进攻型结论。",
    }.get(stage, "风险等级未知，需要复核数据完整性。")


def _stage_strategy(stage: str, has_insufficient: bool) -> str:
    suffix = " 数据缺口补齐前不得把未知项解释为安全。" if has_insufficient else ""
    if stage == "A级":
        return "风险层允许继续比较适用战法，但结论仍需资金、趋势与公告证据共同支持。" + suffix
    if stage == "B级":
        return "先解释全部扣分项，再决定是否继续策略论证。" + suffix
    if stage == "C级":
        return "优先完成风险排除，暂不提升研究结论等级。" + suffix
    return "优先规避风险，不进入进攻型策略论证。" + suffix


def _next_checks(stage: str, risk_points: list[str], insufficient: list[str]) -> list[str]:
    checks = [
        "核验减持规模、执行进度及交易所问询回复是否形成闭环。",
        "复核商誉对应并购标的表现、股权质押变化及最新财报。",
        "使用滚动成交额与换手率确认策略容量和可退出性。",
    ]
    if risk_points:
        checks.insert(0, f"优先解释已触发风险：{'、'.join(risk_points[:3])}。")
    if insufficient:
        checks.insert(0, f"先补齐数据：{'、'.join(insufficient)}。")
    if stage in {"C级", "D级"}:
        checks.append("风险项未解除前仅保留观察性研究，不生成自动交易指令。")
    return checks
