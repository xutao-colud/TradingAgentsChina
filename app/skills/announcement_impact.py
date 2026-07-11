from __future__ import annotations

from app.schemas.report import Announcement, SkillInsight
from app.skills.common import clamp_score


def analyze_announcement_impact(announcements: list[Announcement]) -> SkillInsight:
    score = 50
    evidence: list[str] = []
    risks: list[str] = []
    for item in announcements:
        weight = 14 if item.priority in {"exchange", "company"} else 8
        if item.sentiment == "positive":
            score += weight
        elif item.sentiment == "negative":
            score -= weight + 4
            risks.append(item.summary)
        evidence.append(f"{item.priority}｜{item.sentiment}｜{item.title}")
    final_score = clamp_score(score)
    if final_score >= 70:
        stage = "明显利好"
    elif final_score >= 55:
        stage = "温和正面"
    elif final_score >= 45:
        stage = "中性"
    else:
        stage = "风险公告"
    return SkillInsight(
        skill="公告影响分析",
        category="news",
        stage=stage,
        score=final_score,
        conclusion=f"公告影响为{stage}",
        strategy="交易所和公司公告优先级高于媒体情绪，重大风险公告可直接降级。",
        evidence=evidence or ["未发现公告数据。"],
        risks=risks,
    )

