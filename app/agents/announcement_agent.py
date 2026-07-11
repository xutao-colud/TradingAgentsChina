from __future__ import annotations

from app.agents.common import clamp_score, confidence_from_score
from app.schemas.report import AgentFinding, Announcement


def analyze_announcements(items: list[Announcement]) -> AgentFinding:
    score = 50
    evidence: list[str] = []
    risks: list[str] = []
    source_ids: list[str] = []
    for item in items:
        source_ids.append(item.source_id)
        evidence.append(f"{item.priority}｜{item.title}：{item.summary}")
        if item.sentiment == "positive":
            score += 10 if item.priority in {"exchange", "company"} else 6
        elif item.sentiment == "negative":
            score -= 16 if item.priority in {"exchange", "company"} else 8
            risks.append(item.summary)
    final_score = clamp_score(score)
    conclusion = "公告新闻偏正面" if final_score >= 60 else "公告新闻中性"
    if final_score < 45:
        conclusion = "公告新闻存在明显风险"
    return AgentFinding(
        agent="新闻公告 Agent",
        conclusion=conclusion,
        score=final_score,
        confidence=confidence_from_score(final_score),
        evidence=evidence or ["未发现公告样例数据。"],
        risks=risks,
        counterpoints=["公告优先级高于媒体情绪，但仍需核验原文。"],
        source_ids=source_ids,
    )

