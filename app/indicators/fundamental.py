from __future__ import annotations

from dataclasses import dataclass

from app.schemas.report import FundamentalSnapshot


@dataclass(frozen=True)
class FundamentalAnalysis:
    dupont_margin: float | None
    asset_turnover: float | None
    equity_multiplier: float | None
    dupont_roe: float | None
    cash_conversion: float | None
    non_recurring_profit_impact: float | None
    non_recurring_profit_ratio: float | None
    working_capital_flags: list[str]
    peer_comparison: dict[str, float]
    unavailable_reasons: list[str]


def analyze_fundamental_quality(snapshot: FundamentalSnapshot) -> FundamentalAnalysis:
    missing: list[str] = []
    margin = snapshot.net_profit_margin if snapshot.net_profit_margin is not None else _divide(snapshot.net_income, snapshot.revenue)
    turnover = snapshot.asset_turnover if snapshot.asset_turnover is not None else _divide(snapshot.revenue, snapshot.total_assets)
    multiplier = snapshot.equity_multiplier if snapshot.equity_multiplier is not None else _divide(snapshot.total_assets, snapshot.total_equity)
    if margin is None:
        missing.append(f"缺少{_missing_names(snapshot, ('net_income', 'revenue'))}，无法进行杜邦净利率拆解。")
    if turnover is None:
        missing.append(f"缺少{_missing_names(snapshot, ('revenue', 'total_assets'))}，无法进行资产周转拆解。")
    if multiplier is None:
        missing.append(f"缺少{_missing_names(snapshot, ('total_assets', 'total_equity'))}，无法进行权益乘数拆解。")
    dupont_roe = margin * turnover * multiplier if None not in {margin, turnover, multiplier} else None
    cash_conversion = _divide(snapshot.operating_cash_flow, snapshot.net_income)
    if cash_conversion is None:
        missing.append(f"缺少{_missing_names(snapshot, ('operating_cash_flow', 'net_income'))}，无法核验利润现金含量。")
    non_recurring_impact = snapshot.non_recurring_profit_impact
    if non_recurring_impact is None and snapshot.net_income is not None and snapshot.deducted_net_income is not None:
        non_recurring_impact = snapshot.net_income - snapshot.deducted_net_income
    non_recurring_ratio = snapshot.non_recurring_profit_ratio
    if non_recurring_ratio is None and non_recurring_impact is not None and snapshot.net_income not in {None, 0}:
        non_recurring_ratio = non_recurring_impact / abs(snapshot.net_income) * 100
    if snapshot.deducted_net_income is None:
        missing.append("缺少扣非净利润，无法量化一次性损益影响。")
    flags: list[str] = []
    if snapshot.accounts_receivable is not None and snapshot.revenue:
        flags.append(f"应收/收入：{snapshot.accounts_receivable / snapshot.revenue:.2%}")
    else:
        missing.append("缺少应收或收入，无法核验应收占收入。")
    if snapshot.inventory is not None and snapshot.revenue:
        flags.append(f"存货/收入：{snapshot.inventory / snapshot.revenue:.2%}")
    else:
        missing.append("缺少存货或收入，无法核验存货占收入。")
    comparisons = {
        metric: getattr(snapshot, metric) - benchmark
        for metric, benchmark in snapshot.peer_medians.items()
        if isinstance(getattr(snapshot, metric, None), (int, float))
    }
    if not snapshot.peer_medians:
        missing.extend(
            snapshot.peer_unavailable_reasons
            or ["未取得同业可比样本，不能声明行业排名或相对估值优势。"]
        )
    return FundamentalAnalysis(
        margin,
        turnover,
        multiplier,
        dupont_roe,
        cash_conversion,
        non_recurring_impact,
        non_recurring_ratio,
        flags,
        comparisons,
        missing,
    )


def _divide(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in {None, 0}:
        return None
    return numerator / denominator


def _missing_names(snapshot: FundamentalSnapshot, fields: tuple[str, ...]) -> str:
    labels = {
        "net_income": "净利润",
        "revenue": "营业收入",
        "total_assets": "总资产",
        "total_equity": "股东权益",
        "operating_cash_flow": "经营现金流",
    }
    missing = [labels[field] for field in fields if getattr(snapshot, field) is None]
    return "、".join(missing) or "必要字段"
