from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import median
from typing import Iterable

from app.saas.contracts import StrategyOutcomeRecord


@dataclass(frozen=True)
class StrategyPerformanceSummary:
    playbook_id: str
    eligible_sample_size: int
    average_return_pct: float | None
    median_return_pct: float | None
    win_rate: float | None
    fit_return_correlation: float | None
    evidence_status: str
    interpretation: str
    limitations: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def summarize_strategy_outcomes(
    records: Iterable[StrategyOutcomeRecord],
    min_sample_size: int = 30,
) -> list[StrategyPerformanceSummary]:
    """Compute descriptive, consent-gated associations—not causal performance claims."""
    if min_sample_size < 2:
        raise ValueError("min_sample_size must be at least 2")
    grouped: dict[str, list[StrategyOutcomeRecord]] = {}
    for record in records:
        if not record.aggregate_consent or record.outcome_days <= 0:
            continue
        grouped.setdefault(record.playbook_id, []).append(record)
    return [_summarize_group(playbook, rows, min_sample_size) for playbook, rows in sorted(grouped.items())]


def _summarize_group(playbook_id: str, rows: list[StrategyOutcomeRecord], min_sample_size: int) -> StrategyPerformanceSummary:
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
        interpretation = f"仅有 {sample_size} 条已授权结果，样本不足；不对战法有效性或相关性作结论。"
    elif correlation is None:
        status = "descriptive_only"
        interpretation = "样本已达阈值，但适配分数没有足够变化，无法计算分数与收益的关联。"
    elif correlation > 0:
        status = "observational_positive_association"
        interpretation = "适配分数与结果收益呈正向观察性关联，仍需样本外和摩擦回测验证。"
    elif correlation < 0:
        status = "observational_negative_association"
        interpretation = "适配分数与结果收益呈负向观察性关联，应检查市场状态、选择偏差和规则失效。"
    else:
        status = "no_observed_association"
        interpretation = "当前样本未观察到线性关联，不能据此判断战法无效。"
    return StrategyPerformanceSummary(
        playbook_id=playbook_id,
        eligible_sample_size=sample_size,
        average_return_pct=round(sum(returns) / sample_size, 4) if rows else None,
        median_return_pct=round(float(median(returns)), 4) if rows else None,
        win_rate=round(sum(1 for value in returns if value > 0) / sample_size, 4) if rows else None,
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
