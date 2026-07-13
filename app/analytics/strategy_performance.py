from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import median
from typing import Iterable

from app.saas.contracts import StrategyOutcomeRecord


@dataclass(frozen=True)
class StrategyPerformanceSummary:
    playbook_id: str
    market_regime: str
    eligible_sample_size: int
    average_return_pct: float | None
    median_return_pct: float | None
    positive_outcome_rate: float | None
    fit_return_correlation: float | None
    evidence_status: str
    interpretation: str
    limitations: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AgentReputationSummary:
    agent: str
    market_regime: str
    eligible_sample_size: int
    directional_observation_count: int
    directional_alignment_rate: float | None
    evidence_status: str
    interpretation: str
    limitations: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def summarize_strategy_outcomes(
    records: Iterable[StrategyOutcomeRecord],
    min_sample_size: int = 30,
) -> list[StrategyPerformanceSummary]:
    """Compute consent-gated descriptive observations by playbook and regime."""
    if min_sample_size < 2:
        raise ValueError("min_sample_size must be at least 2")
    grouped: dict[tuple[str, str], list[StrategyOutcomeRecord]] = {}
    for record in records:
        if not record.aggregate_consent or record.outcome_days <= 0:
            continue
        grouped.setdefault((record.playbook_id, record.market_regime), []).append(record)
    return [
        _summarize_group(playbook, regime, rows, min_sample_size)
        for (playbook, regime), rows in sorted(grouped.items())
    ]


def summarize_agent_reputation(
    records: Iterable[StrategyOutcomeRecord],
    min_sample_size: int = 30,
) -> list[AgentReputationSummary]:
    """Describe directional alignment of frozen Agent scores by market regime.

    A score >= 60 is treated as evidence supporting the setup, and <= 40 as
    evidence not supporting it. Neutral scores are excluded rather than being
    forced into a false correct/incorrect label. This is a review metric, never
    a model weight or a claim of predictive ability.
    """
    if min_sample_size < 2:
        raise ValueError("min_sample_size must be at least 2")
    grouped: dict[tuple[str, str], list[tuple[int, float]]] = {}
    for record in records:
        if not record.aggregate_consent:
            continue
        for agent, score in record.agent_scores.items():
            if score >= 60 or score <= 40:
                grouped.setdefault((agent, record.market_regime), []).append((score, record.outcome_return_pct))
    summaries: list[AgentReputationSummary] = []
    for (agent, regime), observations in sorted(grouped.items()):
        sample_size = len(observations)
        aligned = sum(
            1
            for score, outcome in observations
            if (score >= 60 and outcome > 0) or (score <= 40 and outcome <= 0)
        )
        if sample_size < min_sample_size:
            status = "exploratory"
            rate = None
            interpretation = f"仅有 {sample_size} 条已授权方向性观察；不展示 Agent 信誉率。"
        else:
            status = "descriptive_only"
            rate = round(aligned / sample_size, 4)
            interpretation = "该比率仅描述冻结评分方向与记录结果的一致性，不代表预测能力、因果关系或未来表现。"
        summaries.append(
            AgentReputationSummary(
                agent=agent,
                market_regime=regime,
                eligible_sample_size=sample_size,
                directional_observation_count=sample_size,
                directional_alignment_rate=rate,
                evidence_status=status,
                interpretation=interpretation,
                limitations=[
                    "仅纳入用户明确同意聚合的记录，可能存在选择偏差。",
                    "结果可能来自手动录入；必须区分持有期、成本、涨跌停和不可成交情形。",
                    "该指标只能用于复盘和研究质量改进，不能自动改变 Agent 权重或生成交易指令。",
                ],
            )
        )
    return summaries


def _summarize_group(
    playbook_id: str,
    market_regime: str,
    rows: list[StrategyOutcomeRecord],
    min_sample_size: int,
) -> StrategyPerformanceSummary:
    returns = [item.outcome_return_pct for item in rows]
    fit_scores = [item.playbook_fit_score for item in rows]
    sample_size = len(rows)
    correlation = _pearson_correlation(fit_scores, returns)
    limitations = [
        "观察性统计，不代表战法导致收益。",
        "必须纳入失败样本、交易成本、滑点、涨跌停和不可成交情形。",
        "不同持有周期、市场状态和标的池不能直接横向比较。",
    ]
    if sample_size < min_sample_size:
        status = "exploratory"
        positive_rate = None
        interpretation = f"仅有 {sample_size} 条已授权结果；样本不足，不展示正收益比例或战法有效性结论。"
    elif correlation is None:
        status = "descriptive_only"
        positive_rate = round(sum(1 for value in returns if value > 0) / sample_size, 4)
        interpretation = "样本达到阈值，但适配分数没有足够变化；只展示结果分布，不计算分数关联。"
    elif correlation > 0:
        status = "observational_positive_association"
        positive_rate = round(sum(1 for value in returns if value > 0) / sample_size, 4)
        interpretation = "适配分数与记录结果呈正向观察性关联，仍需样本外、成本和滚动回测验证。"
    elif correlation < 0:
        status = "observational_negative_association"
        positive_rate = round(sum(1 for value in returns if value > 0) / sample_size, 4)
        interpretation = "适配分数与记录结果呈负向观察性关联，应检查市场状态、选择偏差和规则失效。"
    else:
        status = "no_observed_association"
        positive_rate = round(sum(1 for value in returns if value > 0) / sample_size, 4)
        interpretation = "当前样本未观察到线性关联，不能据此判断战法无效。"
    return StrategyPerformanceSummary(
        playbook_id=playbook_id,
        market_regime=market_regime,
        eligible_sample_size=sample_size,
        average_return_pct=round(sum(returns) / sample_size, 4) if rows else None,
        median_return_pct=round(float(median(returns)), 4) if rows else None,
        positive_outcome_rate=positive_rate,
        fit_return_correlation=round(correlation, 4) if correlation is not None else None,
        evidence_status=status,
        interpretation=interpretation,
        limitations=limitations,
    )


def _pearson_correlation(xs: list[int], ys: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    x_scale = sum((x - x_mean) ** 2 for x in xs) ** 0.5
    y_scale = sum((y - y_mean) ** 2 for y in ys) ** 0.5
    if x_scale == 0 or y_scale == 0:
        return None
    return numerator / (x_scale * y_scale)
