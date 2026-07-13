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
    working_capital_flags: list[str]
    peer_comparison: dict[str, float]
    unavailable_reasons: list[str]


def analyze_fundamental_quality(snapshot: FundamentalSnapshot) -> FundamentalAnalysis:
    missing: list[str] = []
    margin = _divide(snapshot.net_income, snapshot.revenue)
    turnover = _divide(snapshot.revenue, snapshot.total_assets)
    multiplier = _divide(snapshot.total_assets, snapshot.total_equity)
    if margin is None:
        missing.append("缺少净利润或营业收入，无法进行杜邦净利率拆解。")
    if turnover is None:
        missing.append("缺少营业收入或总资产，无法进行资产周转拆解。")
    if multiplier is None:
        missing.append("缺少总资产或股东权益，无法进行权益乘数拆解。")
    dupont_roe = margin * turnover * multiplier if None not in {margin, turnover, multiplier} else None
    cash_conversion = _divide(snapshot.operating_cash_flow, snapshot.net_income)
    if cash_conversion is None:
        missing.append("缺少经营现金流或净利润，无法核验利润现金含量。")
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
    return FundamentalAnalysis(margin, turnover, multiplier, dupont_roe, cash_conversion, flags, comparisons, missing)


def _divide(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in {None, 0}:
        return None
    return numerator / denominator
