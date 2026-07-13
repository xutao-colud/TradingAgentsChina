from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Callable

from app.config.runtime import load_runtime_settings
from app.rules.trading_rules import daily_limit_pct
from app.schemas.report import DailyPrice, StockProfile


SignalRule = Callable[[tuple[DailyPrice, ...]], bool]


@dataclass(frozen=True)
class BacktestSpec:
    playbook_id: str
    hypothesis: str
    entry_rule: SignalRule
    exit_rule: SignalRule
    maximum_holding_bars: int
    dataset_symbol: str | None = None
    source_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class BacktestTrade:
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    shares: int
    holding_bars: int
    net_return_pct: float
    pnl: float
    market_regime: str


@dataclass(frozen=True)
class RegimeBacktestSummary:
    market_regime: str
    trades: int
    average_return_pct: float | None
    positive_trade_rate: float | None
    win_loss_ratio: float | None
    evidence_status: str


@dataclass(frozen=True)
class BacktestResult:
    playbook_id: str
    hypothesis: str
    initial_cash: float
    final_equity: float
    total_return_pct: float
    maximum_drawdown_pct: float
    closed_trades: int
    positive_trade_rate: float | None
    average_trade_return_pct: float | None
    win_loss_ratio: float | None
    rejected_orders: int
    open_position: bool
    evidence_status: str
    source_ids: list[str] = field(default_factory=list)
    regime_summaries: list[RegimeBacktestSummary] = field(default_factory=list)
    trades: list[BacktestTrade] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class _Position:
    entry_index: int
    entry_date: str
    entry_price: float
    shares: int
    entry_cost: float
    regime: str


def run_backtest(
    profile: StockProfile,
    bars: list[DailyPrice],
    spec: BacktestSpec,
    regimes: dict[str, str] | None = None,
    stress: bool = False,
) -> BacktestResult:
    if spec.maximum_holding_bars < 1:
        raise ValueError("maximum_holding_bars must be positive")
    if spec.dataset_symbol is not None and spec.dataset_symbol != profile.symbol:
        raise ValueError("backtest spec point-in-time dataset does not match the stock profile")
    ordered = sorted(bars, key=lambda item: item.trade_date)
    if len(ordered) < 2:
        raise ValueError("at least two dated bars are required")
    if len({item.trade_date for item in ordered}) != len(ordered):
        raise ValueError("bar dates must be unique")
    config = load_runtime_settings().get("backtest")
    cash = float(config["initial_cash"])
    initial_cash = cash
    slippage = config["slippage_rate"] * (config["stress_slippage_multiplier"] if stress else 1)
    position: _Position | None = None
    pending: str | None = None
    trades: list[BacktestTrade] = []
    rejected = 0
    equity_curve: list[float] = []
    regime_map = regimes or {}

    for index, bar in enumerate(ordered):
        previous = ordered[index - 1] if index > 0 else None
        if pending and previous:
            if not _eligible_open(profile, previous, bar):
                rejected += 1
            elif pending == "buy" and position is None:
                fill = bar.open * (1 + slippage)
                budget = cash * config["position_fraction"]
                shares = int(budget / fill / config["lot_size"]) * config["lot_size"]
                gross = shares * fill
                commission = _commission(gross, config)
                if shares > 0 and gross + commission <= cash:
                    cash -= gross + commission
                    position = _Position(index, bar.trade_date, fill, shares, gross + commission, regime_map.get(bar.trade_date, "unknown"))
                    pending = None
                else:
                    rejected += 1
                    pending = None
            elif pending == "sell" and position is not None and index > position.entry_index:
                fill = bar.open * (1 - slippage)
                gross = position.shares * fill
                costs = _commission(gross, config) + gross * config["stamp_duty_rate"]
                proceeds = gross - costs
                cash += proceeds
                pnl = proceeds - position.entry_cost
                trades.append(BacktestTrade(
                    position.entry_date, bar.trade_date, position.entry_price, fill, position.shares,
                    index - position.entry_index, round(pnl / position.entry_cost * 100, 4), round(pnl, 2), position.regime,
                ))
                position = None
                pending = None

        history = tuple(ordered[: index + 1])
        if index < len(ordered) - 1 and pending is None:
            if position is None and spec.entry_rule(history):
                pending = "buy"
            elif position is not None:
                held = index - position.entry_index + 1
                if spec.exit_rule(history) or held >= spec.maximum_holding_bars:
                    pending = "sell"
        equity_curve.append(cash + (position.shares * bar.close if position else 0.0))

    final_equity = equity_curve[-1]
    returns = [item.net_return_pct for item in trades]
    minimum = int(config["minimum_trades"])
    status = "descriptive_only" if len(trades) >= minimum else "insufficient_sample"
    positive_rate = round(sum(item.pnl > 0 for item in trades) / len(trades), 4) if len(trades) >= minimum else None
    limitations = [
        "回测只验证完全编码的历史假设，不代表未来收益或因果关系。",
        "信号在收盘后形成并使用下一交易日开盘成交，仍需警惕幸存者偏差、复权和停牌数据质量。",
        "滑点、涨跌停和流动性是简化模型；应使用无幸存者偏差数据和多市场状态样本做样本外验证。",
    ]
    if len(trades) < minimum:
        limitations.insert(0, f"仅有 {len(trades)} 笔已平仓样本，低于配置门槛 {minimum}；不展示经验正收益比例。")
    return BacktestResult(
        playbook_id=spec.playbook_id, hypothesis=spec.hypothesis, initial_cash=initial_cash,
        final_equity=round(final_equity, 2), total_return_pct=round((final_equity / initial_cash - 1) * 100, 4),
        maximum_drawdown_pct=round(_maximum_drawdown(equity_curve), 4), closed_trades=len(trades),
        positive_trade_rate=positive_rate,
        average_trade_return_pct=round(sum(returns) / len(returns), 4) if returns else None,
        win_loss_ratio=_win_loss_ratio(trades), rejected_orders=rejected, open_position=position is not None,
        evidence_status=status, source_ids=list(spec.source_ids), regime_summaries=_regime_summaries(trades, minimum), trades=trades, limitations=limitations,
    )


def _eligible_open(profile: StockProfile, previous: DailyPrice, current: DailyPrice) -> bool:
    liquidity = load_runtime_settings().get("market_rules", "liquidity")
    if (
        current.turnover_rate is None
        or current.amount < liquidity["minimum_amount"]
        or current.turnover_rate < liquidity["minimum_turnover_rate"]
    ):
        return False
    move = abs(current.open / previous.close - 1) * 100 if previous.close else 100
    return move < daily_limit_pct(profile)


def _commission(value: float, config: dict[str, object]) -> float:
    return max(float(config["minimum_commission"]), value * float(config["commission_rate"]))


def _maximum_drawdown(values: list[float]) -> float:
    peak = 0.0
    maximum = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            maximum = max(maximum, (peak - value) / peak * 100)
    return maximum


def _win_loss_ratio(trades: list[BacktestTrade]) -> float | None:
    wins = [item.pnl for item in trades if item.pnl > 0]
    losses = [-item.pnl for item in trades if item.pnl < 0]
    if not wins or not losses:
        return None
    return round((sum(wins) / len(wins)) / (sum(losses) / len(losses)), 4)


def _regime_summaries(trades: list[BacktestTrade], minimum: int) -> list[RegimeBacktestSummary]:
    grouped: dict[str, list[BacktestTrade]] = {}
    for trade in trades:
        grouped.setdefault(trade.market_regime, []).append(trade)
    summaries = []
    for regime, rows in sorted(grouped.items()):
        enough = len(rows) >= minimum
        summaries.append(RegimeBacktestSummary(
            regime, len(rows), round(sum(item.net_return_pct for item in rows) / len(rows), 4),
            round(sum(item.pnl > 0 for item in rows) / len(rows), 4) if enough else None,
            _win_loss_ratio(rows), "descriptive_only" if enough else "insufficient_sample",
        ))
    return summaries
