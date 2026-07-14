from __future__ import annotations

from app.agents.common import confidence_from_score
from app.schemas.report import AgentFinding, Announcement, DailyPrice
from app.skills.announcement_impact import analyze_announcement_impact


def analyze_announcements(
    items: list[Announcement],
    prices: list[DailyPrice] | None = None,
    analysis_date: str | None = None,
) -> AgentFinding:
    insight = analyze_announcement_impact(items, prices, analysis_date)
    source_ids = list(dict.fromkeys(item.source_id for item in items if item.source_id))
    return AgentFinding(
        agent="新闻公告 Agent",
        conclusion=insight.conclusion,
        score=insight.score,
        confidence=confidence_from_score(insight.score) if items else 0.0,
        evidence=insight.evidence,
        risks=insight.risks,
        counterpoints=["公告后价格表现是观察性证据；行业、指数和同期事件可能共同影响走势。"],
        invalidation_conditions=["公告原文关键条件与摘要不一致。", "后续更正公告、业绩快报或问询回复改变当前事件状态。"],
        source_ids=source_ids,
        details=insight.details,
    )
