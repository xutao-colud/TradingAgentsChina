from __future__ import annotations

from app.schemas.report import AnalysisReport


def render_markdown(report: AnalysisReport) -> str:
    lines = [
        f"# A股个股智能分析报告：{report.name}（{report.symbol}）",
        "",
        f"- 分析日期：{report.analysis_date}",
        f"- 数据状态：{report.data_status}",
        f"- 规则版本：{report.rule_version}",
        f"- 市场状态：{report.market_regime}",
        f"- 综合结论：{report.conclusion}",
        f"- 风险等级：{report.risk_level}",
        f"- 置信度：{report.confidence:.2f}",
        f"- 操作计划：{report.action_plan}",
        "",
        "## 核心评分",
        "",
        f"- 基本面：{report.fundamental_score}",
        f"- 技术面：{report.technical_score}",
        f"- 资金面：{report.capital_flow_score}",
        f"- 公告新闻：{report.sentiment_score}",
        f"- 题材热点：{report.theme_score}",
        "",
        "## A股领域 Skills",
        "",
    ]
    for insight in report.skill_insights:
        lines.extend(
            [
                f"### {insight.skill}",
                "",
                f"- 类别：{insight.category}",
                f"- 阶段：{insight.stage}",
                f"- 分数：{insight.score}",
                f"- 结论：{insight.conclusion}",
                f"- 策略：{insight.strategy}",
                "- 证据：",
            ]
        )
        lines.extend(f"  - {item}" for item in insight.evidence)
        if insight.risks:
            lines.append("- 风险：")
            lines.extend(f"  - {item}" for item in insight.risks)
        lines.append("")
    if report.model_interpretation:
        lines.extend(["## DeepSeek 解释", "", report.model_interpretation, ""])
    lines.extend([
        "## 多头观点",
        "",
    ])
    lines.extend(_bullet_or_empty(report.bull_case))
    lines.extend(["", "## 空头与风险", ""])
    lines.extend(_bullet_or_empty(report.bear_case or report.risk_factors))
    lines.extend(["", "## A股规则否决/降级条件", ""])
    lines.extend(_bullet_or_empty(report.invalid_conditions))
    lines.extend(["", "## Agent 明细", ""])
    for finding in report.agent_findings:
        lines.extend(
            [
                f"### {finding.agent}",
                "",
                f"- 结论：{finding.conclusion}",
                f"- 分数：{finding.score}",
                f"- 置信度：{finding.confidence:.2f}",
                "- 证据：",
            ]
        )
        lines.extend(f"  - {item}" for item in finding.evidence)
        if finding.risks:
            lines.append("- 风险：")
            lines.extend(f"  - {item}" for item in finding.risks)
        if finding.counterpoints:
            lines.append("- 反例/限制：")
            lines.extend(f"  - {item}" for item in finding.counterpoints)
        if finding.invalidation_conditions:
            lines.append("- 失效条件：")
            lines.extend(f"  - {item}" for item in finding.invalidation_conditions)
        lines.append("")
    lines.extend(["## 数据质量与原始快照", ""])
    if report.data_quality_reports:
        for quality in report.data_quality_reports:
            snapshot_text = ", ".join(quality.snapshot_ids) if quality.snapshot_ids else "无"
            lines.append(
                f"- `{quality.provider}.{quality.dataset}`：{quality.status}，"
                f"有效 {quality.valid_records}/{quality.checked_records}，快照：{snapshot_text}"
            )
            lines.extend(f"  - {issue.severity}: {issue.message}" for issue in quality.issues)
    else:
        lines.append("- 未提供数据质量报告。")
    lines.extend(["", "## 证据来源", ""])
    lines.extend(
        f"- `{source.id}` {source.title}（{source.source_type}，{source.as_of}；"
        f"快照：{', '.join(source.snapshot_ids) if source.snapshot_ids else '无'}）"
        for source in report.evidence_sources
    )
    lines.extend(["", f"> {report.disclaimer}", ""])
    return "\n".join(lines)


def _bullet_or_empty(items: list[str]) -> list[str]:
    if not items:
        return ["- 暂无。"]
    return [f"- {item}" for item in items]
