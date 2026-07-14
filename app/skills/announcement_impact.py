from __future__ import annotations

from app.config.runtime import load_runtime_settings
from app.schemas.report import Announcement, DailyPrice, SkillInsight
from app.skills.common import clamp_score


def analyze_announcement_impact(
    announcements: list[Announcement],
    prices: list[DailyPrice] | None = None,
    analysis_date: str | None = None,
) -> SkillInsight:
    config = load_runtime_settings().get("domain_knowledge", "announcement_timeliness")
    content_config = load_runtime_settings().get("scoring", "announcement")
    all_items = sorted(announcements, key=lambda item: (item.published_at, item.title))
    effective_date = analysis_date or (all_items[-1].published_at if all_items else None)
    ordered = [item for item in all_items if effective_date is None or item.published_at <= effective_date]
    observed_prices = [item for item in list(prices or []) if effective_date is None or item.trade_date <= effective_date]
    score = float(content_config["base"])
    content_impact = 0.0
    evidence: list[str] = []
    risks: list[str] = []
    for item in ordered:
        if item.sentiment == "positive":
            content_impact += content_config["official_positive"] if item.priority in {"exchange", "company"} else content_config["other_positive"]
        elif item.sentiment == "negative":
            content_impact -= content_config["official_negative"] if item.priority in {"exchange", "company"} else content_config["other_negative"]
    maximum_content_impact = float(config["maximum_content_impact"])
    score += max(-maximum_content_impact, min(maximum_content_impact, content_impact))

    reactions = _market_reactions(ordered, observed_prices, config)
    for reaction in reactions:
        if reaction["pattern"] == "high_open_fade":
            score -= float(config["fade_reaction_penalty"])
        elif reaction["pattern"] == "sustained_rise":
            score += float(config["positive_reaction_impact"])
        evidence.append(
            f"公告后反应｜{reaction['title']}：{reaction['pattern_label']}；"
            f"首个可观察交易日 {reaction['reaction_date']} 高开 {reaction['opening_gap_pct']:+.2f}%，"
            f"收盘相对开盘 {reaction['close_from_open_pct']:+.2f}%。"
        )

    forecast_checks = _forecast_checks(ordered, config)
    for check in forecast_checks:
        if check["actual_vs_forecast"] == "above":
            score += float(config["forecast_above_impact"])
        elif check["actual_vs_forecast"] == "below":
            score -= float(config["forecast_below_penalty"])
        evidence.append(f"业绩核验｜{check['report_period']}：{check['description']}。")

    inquiry_checks = _inquiry_checks(ordered, config)
    unresolved = [item for item in inquiry_checks if item["status"] == "unanswered"]
    score -= len(unresolved) * float(config["unanswered_inquiry_penalty"])
    evidence.extend(f"问询跟踪｜{item['title']}：{item['description']}。" for item in inquiry_checks)
    if unresolved:
        risks.append(f"存在 {len(unresolved)} 条在当前公告窗口内未匹配到回复的问询/关注函。")

    for item in ordered:
        evidence.append(f"{item.published_at}｜{item.priority}｜{item.sentiment}｜{item.title}")
    if ordered and not reactions:
        risks.append("缺少公告后交易日或价格历史，无法判断高开低走、持续上涨等市场反应。")
    if not ordered:
        risks.append("未获得可追溯公告，不能把公告缺失解释为公司没有事件风险。")
    risks.append("公告后价格变化仅为时间关联，不证明公告造成该走势。")
    risks.append("公告发布时间缺少时分秒时，统一从下一交易日开始观察，可能晚于真实首次反应。")

    final_score = clamp_score(score)
    if unresolved or any(item["actual_vs_forecast"] == "below" for item in forecast_checks):
        stage = "事件风险待闭环"
    elif any(item["pattern"] == "high_open_fade" for item in reactions):
        stage = "利好兑现分歧"
    elif any(item["pattern"] == "sustained_rise" for item in reactions):
        stage = "市场反应持续"
    elif ordered:
        stage = "公告影响待验证"
    else:
        stage = "数据不足"
    return SkillInsight(
        skill="公告影响分析",
        category="news",
        stage=stage,
        score=final_score,
        conclusion=f"公告时间线状态为{stage}；结论同时考虑文本、公告后市场反应和事件闭环。",
        strategy="优先核验公告原文和未闭环问询；价格反应只作观察性证据，不生成交易指令。",
        evidence=evidence or ["未发现可追溯公告数据。"],
        risks=risks,
        details={
            "analysis_date": effective_date,
            "market_reactions": reactions,
            "forecast_checks": forecast_checks,
            "inquiry_checks": inquiry_checks,
            "source_ids": _unique([item.source_id for item in ordered]),
        },
    )


def _market_reactions(
    announcements: list[Announcement],
    prices: list[DailyPrice],
    config: dict[str, object],
) -> list[dict[str, object]]:
    ordered_prices = sorted(prices, key=lambda item: item.trade_date)
    horizons = [int(item) for item in config["reaction_horizons"]]
    results: list[dict[str, object]] = []
    batches: dict[str, list[Announcement]] = {}
    for item in announcements:
        batches.setdefault(item.published_at, []).append(item)
    for published_at, batch in sorted(batches.items()):
        event_index = next((index for index, price in enumerate(ordered_prices) if price.trade_date > published_at), None)
        if event_index is None or event_index == 0:
            continue
        previous_close = ordered_prices[event_index - 1].close
        event_price = ordered_prices[event_index]
        if previous_close == 0 or event_price.open == 0:
            continue
        opening_gap = (event_price.open / previous_close - 1) * 100
        close_from_open = (event_price.close / event_price.open - 1) * 100
        returns: dict[str, float | None] = {}
        for horizon in horizons:
            target_index = event_index + horizon - 1
            returns[f"{horizon}d"] = (
                (ordered_prices[target_index].close / previous_close - 1) * 100
                if target_index < len(ordered_prices)
                else None
            )
        available = [value for value in returns.values() if value is not None]
        if opening_gap >= float(config["high_open_gap_pct"]) and close_from_open <= -float(config["fade_from_open_pct"]):
            pattern, label = "high_open_fade", "高开低走"
        elif available and all(value >= 0 for value in available) and available[-1] >= float(config["sustained_rise_min_pct"]):
            pattern, label = "sustained_rise", "持续上涨"
        else:
            pattern, label = "mixed", "反应分歧/未定型"
        results.append({
            "source_ids": [item.source_id for item in batch],
            "title": batch[0].title if len(batch) == 1 else f"同日公告{len(batch)}条：{batch[0].title} 等",
            "published_at": published_at,
            "reaction_date": event_price.trade_date,
            "opening_gap_pct": opening_gap,
            "close_from_open_pct": close_from_open,
            "forward_returns": returns,
            "pattern": pattern,
            "pattern_label": label,
        })
    return results


def _forecast_checks(announcements: list[Announcement], config: dict[str, object]) -> list[dict[str, object]]:
    periods = sorted({item.report_period for item in announcements if item.report_period})
    results: list[dict[str, object]] = []
    tolerance = float(config["forecast_revision_tolerance_pct"]) / 100
    for period in periods:
        forecasts = [
            item for item in announcements
            if item.report_period == period and item.event_type == "earnings_forecast"
            and item.forecast_net_profit_min_yuan is not None and item.forecast_net_profit_max_yuan is not None
        ]
        actuals = [
            item for item in announcements
            if item.report_period == period and item.event_type in {"earnings_express", "earnings_actual"} and item.actual_net_profit_yuan is not None
        ]
        forecasts.sort(key=lambda item: item.published_at)
        actuals.sort(key=lambda item: item.published_at)
        if not forecasts:
            continue
        first = forecasts[0]
        latest = forecasts[-1]
        first_mid = (float(first.forecast_net_profit_min_yuan) + float(first.forecast_net_profit_max_yuan)) / 2
        latest_mid = (float(latest.forecast_net_profit_min_yuan) + float(latest.forecast_net_profit_max_yuan)) / 2
        revision = "unchanged"
        if first_mid and latest_mid > first_mid + abs(first_mid) * tolerance:
            revision = "up"
        elif first_mid and latest_mid < first_mid - abs(first_mid) * tolerance:
            revision = "down"
        actual_status = "unavailable"
        actual = actuals[-1].actual_net_profit_yuan if actuals else None
        if actual is not None:
            if actual > float(latest.forecast_net_profit_max_yuan):
                actual_status = "above"
            elif actual < float(latest.forecast_net_profit_min_yuan):
                actual_status = "below"
            else:
                actual_status = "within"
        results.append({
            "report_period": period,
            "forecast_revision": revision,
            "actual_vs_forecast": actual_status,
            "forecast_min_yuan": latest.forecast_net_profit_min_yuan,
            "forecast_max_yuan": latest.forecast_net_profit_max_yuan,
            "actual_net_profit_yuan": actual,
            "description": f"预告修正={revision}，快报/实际值相对最新预告区间={actual_status}",
        })
    return results


def _inquiry_checks(announcements: list[Announcement], config: dict[str, object]) -> list[dict[str, object]]:
    inquiries = [item for item in announcements if item.event_type == "inquiry"]
    replies = [item for item in announcements if item.event_type == "inquiry_reply"]
    results: list[dict[str, object]] = []
    for inquiry in inquiries:
        candidates = [
            reply for reply in replies
            if reply.published_at >= inquiry.published_at
            and _title_similarity(inquiry.title, reply.title, config) >= float(config["thread_similarity_threshold"])
        ]
        reply = min(candidates, key=lambda item: item.published_at, default=None)
        results.append({
            "source_id": inquiry.source_id,
            "title": inquiry.title,
            "published_at": inquiry.published_at,
            "status": "answered" if reply else "unanswered",
            "reply_source_id": reply.source_id if reply else None,
            "reply_date": reply.published_at if reply else None,
            "description": f"已匹配回复，回复日 {reply.published_at}" if reply else "当前公告窗口内未匹配到可验证回复",
        })
    return results


def _title_similarity(left: str, right: str, config: dict[str, object]) -> float:
    for phrase in config["thread_stop_phrases"]:
        left = left.replace(phrase, "")
        right = right.replace(phrase, "")
    left_pairs = {left[index:index + 2] for index in range(max(0, len(left) - 1))}
    right_pairs = {right[index:index + 2] for index in range(max(0, len(right) - 1))}
    union = left_pairs | right_pairs
    return len(left_pairs & right_pairs) / len(union) if union else 0.0


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
