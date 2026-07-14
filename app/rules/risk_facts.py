from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

from app.config.runtime import load_runtime_settings
from app.schemas.report import (
    Announcement,
    AshareMarketSignals,
    CorporateEvent,
    DataQualityReport,
    EvidenceSource,
    StockProfile,
)


def enrich_stock_profile_risks(
    profile: StockProfile,
    signals: AshareMarketSignals | None,
    announcements: list[Announcement],
    evidence_sources: list[EvidenceSource],
    quality_reports: list[DataQualityReport],
    analysis_date: str,
) -> StockProfile:
    """Attach point-in-time A-share risk facts without synthesizing neutral data."""

    config = load_runtime_settings().get("domain_knowledge", "risk_scanner")
    source_by_id = {item.id: item for item in evidence_sources if item.as_of <= analysis_date}

    reduction_cutoff = date.fromisoformat(analysis_date) - timedelta(
        days=int(config["holder_reduction_lookback_days"])
    )
    reduction_events = _deduplicate_events([
        item
        for item in (signals.corporate_events if signals else [])
        if item.event_type == "股东增减持"
        and item.impact == "negative"
        and item.source_id in source_by_id
        and reduction_cutoff <= date.fromisoformat(item.published_at) <= date.fromisoformat(analysis_date)
    ])
    reduction_coverage_ids = sorted(
        source_id
        for source_id in source_by_id
        if source_id == "holder-trade-coverage-tushare-001"
    )
    reduction_quality_ok = any(
        item.provider == "tushare" and item.dataset == "holder_trades" and item.status == "passed"
        for item in quality_reports
    ) and bool(reduction_coverage_ids)
    if reduction_events:
        reduction_value: bool | None = True
        reduction_count: int | None = len(reduction_events)
        reduction_as_of = max(item.published_at for item in reduction_events)
        reduction_source_ids = sorted({item.source_id for item in reduction_events})
    elif reduction_quality_ok:
        reduction_value = False
        reduction_count = 0
        reduction_as_of = analysis_date
        reduction_source_ids = reduction_coverage_ids
    else:
        reduction_value = None
        reduction_count = None
        reduction_as_of = None
        reduction_source_ids = []

    inquiry_cutoff = date.fromisoformat(analysis_date) - timedelta(days=int(config["inquiry_lookback_days"]))
    inquiries = _deduplicate_announcements([
        item
        for item in announcements
        if item.event_type == "inquiry"
        and item.source_id in source_by_id
        and inquiry_cutoff <= date.fromisoformat(item.published_at) <= date.fromisoformat(analysis_date)
    ])
    inquiry_coverage_ids = [
        source_id
        for source_id in source_by_id
        if source_id == "announcement-coverage-cninfo-001"
    ]
    inquiry_quality_ok = any(
        item.provider == "akshare" and item.dataset == "announcements" and item.status == "passed"
        for item in quality_reports
    ) and bool(inquiry_coverage_ids)
    if inquiries:
        inquiry_count: int | None = len(inquiries)
        inquiry_as_of = max(item.published_at for item in inquiries)
        inquiry_source_ids = sorted({item.source_id for item in inquiries})
    elif inquiry_quality_ok:
        inquiry_count = 0
        inquiry_as_of = analysis_date
        inquiry_source_ids = inquiry_coverage_ids
    else:
        inquiry_count = None
        inquiry_as_of = None
        inquiry_source_ids = []

    return replace(
        profile,
        major_shareholder_reduction=reduction_value,
        major_shareholder_reduction_count=reduction_count,
        major_shareholder_reduction_as_of=reduction_as_of,
        major_shareholder_reduction_source_ids=reduction_source_ids,
        inquiry_count=inquiry_count,
        inquiry_as_of=inquiry_as_of,
        inquiry_source_ids=inquiry_source_ids,
    )


def _deduplicate_events(items: list[CorporateEvent]) -> list[CorporateEvent]:
    return list({
        (getattr(item, "published_at"), getattr(item, "title"), getattr(item, "source_id")): item
        for item in items
    }.values())


def _deduplicate_announcements(items: list[Announcement]) -> list[Announcement]:
    return list({(item.published_at, item.title, item.source_id): item for item in items}.values())
