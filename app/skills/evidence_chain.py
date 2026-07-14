from __future__ import annotations

from app.schemas.report import AgentFinding, EvidenceSource, SkillInsight
from app.skills.common import clamp_score


def assess_evidence_chain_quality(
    findings: list[AgentFinding],
    evidence_sources: list[EvidenceSource],
    derived_insights: list[SkillInsight] | None = None,
) -> SkillInsight:
    source_by_id = {source.id: source for source in evidence_sources}
    total_agents = max(1, len(findings))
    agents_with_evidence = 0
    agents_with_sources = 0
    agents_with_counterpoints = 0
    agents_with_risks = 0
    agents_with_invalidation = 0
    referenced_source_ids: set[str] = set()
    risks: list[str] = []
    penalty = 0

    for finding in findings:
        if finding.evidence:
            agents_with_evidence += 1
        else:
            penalty += 14
            risks.append(f"{finding.agent} 缺少证据。")

        if finding.source_ids:
            agents_with_sources += 1
            referenced_source_ids.update(finding.source_ids)
        else:
            penalty += 14
            risks.append(f"{finding.agent} 缺少 source_ids，结论不可追溯。")

        unknown_sources = [source_id for source_id in finding.source_ids if source_id not in source_by_id]
        if unknown_sources:
            penalty += min(18, len(unknown_sources) * 6)
            risks.append(f"{finding.agent} 引用了未知来源：{', '.join(unknown_sources)}。")

        missing_source_time = [
            source_id
            for source_id in finding.source_ids
            if source_id in source_by_id and not source_by_id[source_id].as_of
        ]
        if missing_source_time:
            penalty += min(12, len(missing_source_time) * 4)
            risks.append(f"{finding.agent} 的部分来源缺少 as_of 时间。")

        if finding.counterpoints:
            agents_with_counterpoints += 1
        else:
            penalty += 10
            risks.append(f"{finding.agent} 缺少反证，不能说明结论边界。")

        if finding.risks:
            agents_with_risks += 1
        else:
            penalty += 10
            risks.append(f"{finding.agent} 缺少风险说明。")

        if finding.invalidation_conditions:
            agents_with_invalidation += 1
        else:
            penalty += 12
            risks.append(f"{finding.agent} 缺少失效条件，结论不可复盘。")

        if not 0 <= finding.confidence <= 1:
            penalty += 10
            risks.append(f"{finding.agent} 的 confidence 不在 0-1 区间。")

    skill_source_ids = {
        str(source_id)
        for insight in derived_insights or []
        for source_id in insight.details.get("source_ids", [])
        if source_id
    }
    referenced_source_ids.update(skill_source_ids)
    unknown_skill_sources = sorted(skill_source_ids - set(source_by_id))
    if unknown_skill_sources:
        penalty += min(18, len(unknown_skill_sources) * 6)
        risks.append(f"确定性 Skill 引用了未知来源：{', '.join(unknown_skill_sources)}。")

    unused_sources = [source.id for source in evidence_sources if source.id not in referenced_source_ids]
    if unused_sources:
        penalty += min(8, len(unused_sources) * 2)
        risks.append(f"存在未被 Agent 引用的证据来源：{', '.join(unused_sources[:4])}。")

    score = clamp_score(100 - penalty)
    if score >= 85:
        stage = "完整"
        conclusion = "证据链完整，当前报告具备可追溯基础"
        strategy = "可以进入策略比较与风险审查，但仍需核验真实数据源。"
    elif score >= 70:
        stage = "可用"
        conclusion = "证据链基本可用，但仍有少量可追溯性缺口"
        strategy = "保持结论克制，优先补齐未引用或低质量来源。"
    elif score >= 55:
        stage = "待补证据"
        conclusion = "证据链存在明显缺口，不宜输出强结论"
        strategy = "将最终结论限制在观察级别，先补齐来源和反证。"
    else:
        stage = "不足"
        conclusion = "证据链不足，当前报告只能作为草稿"
        strategy = "暂停强结论，补齐数据来源、时间戳、反证和风险。"

    return SkillInsight(
        skill="证据链完整性",
        category="quality",
        stage=stage,
        score=score,
        conclusion=conclusion,
        strategy=strategy,
        evidence=[
            f"Agent证据覆盖 {agents_with_evidence}/{total_agents}",
            f"Agent来源覆盖 {agents_with_sources}/{total_agents}",
            f"Agent反证覆盖 {agents_with_counterpoints}/{total_agents}",
            f"Agent风险覆盖 {agents_with_risks}/{total_agents}",
            f"Agent失效条件覆盖 {agents_with_invalidation}/{total_agents}",
            f"证据来源数量 {len(evidence_sources)}",
            f"Skill 来源引用数量 {len(skill_source_ids)}",
        ],
        risks=risks,
    )
