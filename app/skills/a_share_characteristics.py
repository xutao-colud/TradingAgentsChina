from __future__ import annotations

from app.config.runtime import load_runtime_settings
from app.schemas.report import MarketContext, SkillInsight
from app.skills.common import clamp_score


def analyze_a_share_characteristics(context: MarketContext) -> SkillInsight:
    config = load_runtime_settings().get("domain_knowledge", "a_share_characteristics")
    required = {
        "sealed_limit_up_rate": context.sealed_limit_up_rate,
        "failed_breakout_rate": context.failed_breakout_rate,
        "one_price_limit_up_count": context.one_price_limit_up_count,
        "broken_limit_up_count": context.broken_limit_up_count,
    }
    missing = [name for name, value in required.items() if value is None]
    ladder_is_complete = len(context.board_ladder) >= int(config["minimum_ladder_levels"])
    if missing or not ladder_is_complete or context.data_status != "verified":
        return SkillInsight(
            skill="A股涨停结构",
            category="market",
            stage="数据不足",
            score=load_runtime_settings().get("scoring", "data_readiness", "insufficient_score"),
            conclusion="涨停封板、一字板或连板梯队数据不完整，不能解释短线情绪结构。",
            strategy="补齐同一交易日的官方涨停与炸板池后重算，不把缺失值当作零。",
            evidence=[
                f"缺失字段：{', '.join(missing) if missing else '无'}",
                f"连板梯队层数：{len(context.board_ladder)} / {config['minimum_ladder_levels']}",
                f"数据时间：{context.as_of}",
            ],
            risks=list(context.unavailable_reasons) or ["涨停池接口缺失时不得生成情绪强弱结论。"],
            details={"mode": "a_share_characteristics", "admitted": False, "source_ids": [], "as_of": context.as_of},
        )

    sealed_rate = float(context.sealed_limit_up_rate)
    failed_rate = float(context.failed_breakout_rate)
    high_board_count = sum(
        count
        for label, count in context.board_ladder.items()
        if label in set(config["high_board_labels"])
    )
    score = float(config["neutral_score"])
    score += (sealed_rate - float(config["seal_rate_center_pct"])) * float(config["seal_rate_weight"])
    score += min(float(config["one_price_score_cap"]), int(context.one_price_limit_up_count) * float(config["one_price_weight"]))
    score += min(float(config["high_board_score_cap"]), high_board_count * float(config["high_board_weight"]))
    score -= failed_rate * float(config["failed_breakout_weight"])
    final_score = clamp_score(score)
    stage = (
        "封板强"
        if sealed_rate >= float(config["strong_seal_rate_pct"])
        else "封板弱"
        if sealed_rate < float(config["weak_seal_rate_pct"])
        else "封板分歧"
    )
    ladder = " / ".join(f"{label}:{count}" for label, count in context.board_ladder.items())
    return SkillInsight(
        skill="A股涨停结构",
        category="market",
        stage=stage,
        score=final_score,
        conclusion=f"当前涨停结构为{stage}；该结论只描述短线情绪，不代表未来收益。",
        strategy="仅把封板质量和梯队完整度作为市场状态证据，并与题材、资金连续性及风险条件交叉核验。",
        evidence=[
            f"封板率 {sealed_rate:.1f}%（封死涨停 / 触及涨停）",
            f"真实炸板率 {failed_rate:.1f}%，炸板 {context.broken_limit_up_count} 家",
            f"一字板 {context.one_price_limit_up_count} 家",
            f"连板梯队 {ladder}",
            f"数据时间：{context.as_of}",
        ],
        risks=[
            "涨跌停池不含 ST 股票，口径不能直接代表全市场。",
            "一字板数量高可能代表一致性，也可能意味着可交易性差。",
            *context.unavailable_reasons,
        ],
        details={
            "mode": "a_share_characteristics",
            "admitted": True,
            "sealed_limit_up_rate": sealed_rate,
            "failed_breakout_rate": failed_rate,
            "one_price_limit_up_count": context.one_price_limit_up_count,
            "broken_limit_up_count": context.broken_limit_up_count,
            "board_ladder": dict(context.board_ladder),
            "source_ids": ["market-001"],
            "as_of": context.as_of,
        },
    )
