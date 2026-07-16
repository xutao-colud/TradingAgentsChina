from __future__ import annotations

from app.config.runtime import load_runtime_settings
from app.indicators.market_breadth import evaluate_market_breadth_confirmation
from app.schemas.report import MarketContext, SkillInsight
from app.skills.common import clamp_score


def confirm_market_breadth(context: MarketContext) -> SkillInsight:
    result = evaluate_market_breadth_confirmation(context)
    base_score = float(load_runtime_settings().get("domain_knowledge", "market_breadth_confirmation", "neutral_score"))
    return SkillInsight(
        skill="市场广度交叉核验",
        category="market",
        stage=result.stage,
        score=clamp_score(base_score + result.score_adjustment),
        conclusion=(
            "市场横截面数据不足，不能判断指数是否被少数权重股扭曲。"
            if result.stage == "数据不足"
            else f"指数、等权广度、成交额和涨跌停反馈处于{result.stage}状态。"
        ),
        strategy=(
            "补齐同一时点全市场个股涨跌与成交额后重算。"
            if result.stage == "数据不足"
            else "只在指数、等权广度和涨跌停反馈相互确认时提高市场状态置信度。"
        ),
        evidence=result.evidence,
        risks=result.risks,
        details={
            "mode": "market_breadth_cross_validation",
            "confidence_cap": result.confidence_cap,
            "counterpoints": result.counterpoints,
            "missing_fields": result.missing_fields,
            "source_ids": ["market-001"] if result.stage != "数据不足" else [],
            "as_of": context.as_of,
        },
    )
