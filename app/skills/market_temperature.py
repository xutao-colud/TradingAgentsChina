from __future__ import annotations

from app.config.runtime import load_runtime_settings
from app.schemas.report import MarketContext, SkillInsight
from app.skills.common import clamp_score, stage_by_score


def assess_market_temperature(context: MarketContext) -> SkillInsight:
    config = load_runtime_settings().get("scoring", "market_temperature")
    required = {
        "index_change_pct": context.index_change_pct,
        "total_amount": context.total_amount,
        "advancers": context.advancers,
        "decliners": context.decliners,
        "limit_up_count": context.limit_up_count,
        "limit_down_count": context.limit_down_count,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing or context.data_status != "verified":
        return SkillInsight(
            skill="A股市场温度计",
            category="market",
            stage="数据不足",
            score=load_runtime_settings().get("scoring", "data_readiness", "insufficient_score"),
            conclusion="市场温度所需的全市场宽度或涨跌停数据不完整。",
            strategy="暂停市场温度和战法适配判断，补齐同一交易日的全市场数据后重算。",
            evidence=[f"缺失字段：{', '.join(missing) if missing else '无'}", f"市场数据状态：{context.data_status}"],
            risks=list(context.unavailable_reasons) or ["缺失值未按零值参与评分。"],
            details={"missing_fields": missing, "as_of": context.as_of},
        )

    advancers = int(context.advancers)
    decliners = int(context.decliners)
    breadth = advancers / max(1, advancers + decliners)
    amount_score = min(float(config["amount_cap"]), float(context.total_amount) / float(config["amount_divisor"]))
    limit_score = min(float(config["limit_up_cap"]), int(context.limit_up_count) / float(config["limit_up_divisor"])) - min(
        float(config["limit_down_cap"]), int(context.limit_down_count) / float(config["limit_down_divisor"])
    )
    score = (
        float(config["base_score"])
        + float(context.index_change_pct) * float(config["index_change_weight"])
        + (breadth - float(config["breadth_center"])) * float(config["breadth_weight"])
        + amount_score
        + limit_score
    )
    final_score = clamp_score(score)
    stage = stage_by_score(final_score, "防守", "震荡", "震荡修复", "进攻")
    strategy = {
        "进攻": "可提高观察密度，但仍避免情绪高潮后的追高。",
        "震荡修复": "轻仓试错，优先选择有业绩和资金共振的方向。",
        "震荡": "等待主线确认，控制频率。",
        "防守": "以风险排查和现金仓位为主。",
    }[stage]
    return SkillInsight(
        skill="A股市场温度计",
        category="market",
        stage=stage,
        score=final_score,
        conclusion=f"市场温度处于{stage}区间",
        strategy=strategy,
        evidence=[
            f"成交额 {float(context.total_amount) / float(config['amount_display_divisor']):.0f} 亿元",
            f"上涨比例 {breadth * 100:.1f}%",
            f"涨停/跌停 {context.limit_up_count}/{context.limit_down_count}",
            f"{context.index_name}涨跌幅 {float(context.index_change_pct):.2f}%",
        ],
        risks=["市场温度反映整体环境，不能替代个股风险审查。", *context.unavailable_reasons],
        details={"as_of": context.as_of},
    )
