from __future__ import annotations

from app.schemas.report import DailyPrice, DataQualityReport, EvidenceSource, SkillInsight
from app.config.runtime import load_runtime_settings
from app.indicators.technical import required_history_bars


_SAMPLE_TYPES = {"sample", "offline_sample"}


def assess_data_readiness(
    evidence_sources: list[EvidenceSource],
    analysis_date: str,
    prices: list[DailyPrice],
    quality_reports: list[DataQualityReport] | None = None,
) -> SkillInsight:
    """Evaluate whether deterministic inputs are sufficient for a research result.

    Structural traceability and data validity are separate checks. This gate
    prevents a report from treating fixtures, unavailable feeds, stale prices,
    or an insufficient K-line history as if they were production facts.
    """
    config = load_runtime_settings().get("scoring", "data_readiness")
    minimum_price_bars = max(config["minimum_daily_bars"], required_history_bars())
    required_source_ids = tuple(config["required_source_ids"])
    time_sensitive_source_ids = set(config["time_sensitive_source_ids"])
    by_id = {item.id: item for item in evidence_sources}
    risks: list[str] = []
    evidence: list[str] = []
    missing = [source_id for source_id in required_source_ids if source_id not in by_id]
    unavailable: list[str] = []
    sample: list[str] = []
    time_mismatch: list[str] = []
    reports = list(quality_reports or [])
    blocking_quality_failures = [
        item for item in reports if item.status == "failed" and item.blocking
    ]
    quality_warnings = [
        item for item in reports if item.status == "warning" or (item.status == "failed" and not item.blocking)
    ]

    evidence.extend(
        f"quality:{item.provider}.{item.dataset}={item.status} ({item.valid_records}/{item.checked_records})"
        for item in reports
    )

    for source_id in required_source_ids:
        source = by_id.get(source_id)
        if source is None:
            continue
        evidence.append(f"{source_id}: {source.source_type} @ {source.as_of}")
        if source.source_type == "unavailable":
            unavailable.append(source_id)
        elif source.source_type in _SAMPLE_TYPES:
            sample.append(source_id)
        if source_id in time_sensitive_source_ids and source.as_of != analysis_date:
            time_mismatch.append(source_id)

    if missing:
        risks.append(f"缺少关键数据源：{', '.join(missing)}。")
    if unavailable:
        risks.append(f"关键数据源不可用：{', '.join(unavailable)}。")
    if sample:
        risks.append(f"关键输入包含样例/离线数据：{', '.join(sample)}；不得表述为实时或真实市场事实。")
    if time_mismatch:
        risks.append(f"时效性不匹配：{', '.join(time_mismatch)} 的来源时间不等于分析日期。")
    if len(prices) < minimum_price_bars:
        risks.append(
            f"日线数量仅 {len(prices)}，少于配置要求的 {minimum_price_bars} 条；"
            "长周期均线、收益和成本分布不得形成强结论。"
        )
    if blocking_quality_failures:
        risks.append(
            "阻断型数据质量校验失败："
            + ", ".join(f"{item.provider}.{item.dataset}" for item in blocking_quality_failures)
            + "。"
        )
    if quality_warnings:
        risks.append(
            "非阻断数据质量告警："
            + ", ".join(f"{item.provider}.{item.dataset}:{item.status}" for item in quality_warnings)
            + "；相关维度不得生成强结论。"
        )

    hard_failure = bool(
        missing
        or unavailable
        or time_mismatch
        or len(prices) < minimum_price_bars
        or blocking_quality_failures
    )
    if hard_failure:
        stage = "数据不足"
        score = config["insufficient_score"]
        conclusion = "关键数据不可用、时点不匹配或历史不足；当前只能保存为待补数据草稿。"
        strategy = "补齐同一分析日期的行情、资金和市场宽度来源后，再运行个股与战法判断。"
    elif len(sample) == len(required_source_ids):
        stage = "样例数据"
        score = config["sample_score"]
        conclusion = "当前报告基于离线样例数据，只用于流程演示和回归测试。"
        strategy = "不得将该报告用于市场事实、策略评价或用户结果统计。"
    elif sample:
        stage = "混合数据"
        score = config["mixed_score"]
        conclusion = "报告混合了真实与样例来源；可检查流程和待验证假设，但不能形成强结论。"
        strategy = "优先接入缺失的生产来源，并在来源一致后重新生成报告。"
    elif quality_warnings:
        stage = "质量告警"
        score = config["quality_warning_score"]
        conclusion = "核心数据可继续研究，但部分可选数据为空、请求失败或质量不足；相关结论必须降级。"
        strategy = "保留已验证维度，隐藏或弱化存在质量告警的龙虎榜、两融等结论，并等待可回放快照补齐。"
    else:
        stage = "已核验"
        score = config["verified_score"]
        conclusion = "关键来源可用、时间对齐且日线历史满足基础趋势计算要求。"
        strategy = "可以进入证据链、风险和战法比较；新公告或盘中数据到达后仍需重新核验。"

    return SkillInsight(
        skill="数据就绪性审查",
        category="data_quality",
        stage=stage,
        score=score,
        conclusion=conclusion,
        strategy=strategy,
        evidence=evidence + [f"日线数量：{len(prices)}"],
        risks=risks,
        details={
            "required_source_ids": list(required_source_ids),
            "missing_source_ids": missing,
            "unavailable_source_ids": unavailable,
            "sample_source_ids": sample,
            "time_mismatch_source_ids": time_mismatch,
            "daily_price_count": len(prices),
            "required_daily_price_count": minimum_price_bars,
            "blocking_quality_failures": [f"{item.provider}.{item.dataset}" for item in blocking_quality_failures],
            "quality_warnings": [f"{item.provider}.{item.dataset}:{item.status}" for item in quality_warnings],
            "quality_report_count": len(reports),
            "confidence_cap": round(score / 100, 2),
            "mode": "data_readiness",
        },
    )
