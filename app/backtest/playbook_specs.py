from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.backtest.datasets import PointInTimeDataset
from app.backtest.engine import BacktestSpec
from app.config.runtime import load_runtime_settings
from app.playbooks.catalog import get_playbook
from app.schemas.report import DailyPrice


@dataclass(frozen=True)
class PlaybookBacktestCapability:
    playbook_id: str
    supported: bool
    required_dataset: list[str]
    reason: str
    input_mode: str


def describe_backtest_capability(playbook_id: str) -> PlaybookBacktestCapability:
    get_playbook(playbook_id)
    required = list(load_runtime_settings().get("backtest", "playbook_rules", playbook_id, "required_datasets"))
    if playbook_id == "trend_core":
        return PlaybookBacktestCapability(
            playbook_id,
            True,
            required,
            "已提供完全编码的价格/量能基础假设。",
            "price_history",
        )
    return PlaybookBacktestCapability(
        playbook_id,
        True,
        required,
        "已提供时点化数据契约；只有实际数据覆盖完整时才允许构建规格。",
        "point_in_time_dataset",
    )


def assess_dataset_coverage(playbook_id: str, dataset: PointInTimeDataset) -> list[str]:
    get_playbook(playbook_id)
    available = dataset.coverage()
    required = load_runtime_settings().get("backtest", "playbook_rules", playbook_id, "required_datasets")
    return [item for item in required if item not in available]


def build_price_playbook_spec(playbook_id: str) -> BacktestSpec:
    if playbook_id != "trend_core":
        capability = describe_backtest_capability(playbook_id)
        raise ValueError(
            f"{playbook_id} requires {capability.input_mode}; price-only backtests are rejected. "
            f"Required: {', '.join(capability.required_dataset)}"
        )
    playbook = get_playbook(playbook_id)
    config = load_runtime_settings().get("backtest", "playbook_rules", playbook_id)
    ma_window = int(config["moving_average_window"])
    volume_window = int(config["volume_window"])

    def entry(history: tuple[DailyPrice, ...]) -> bool:
        required = max(ma_window, volume_window) + 1
        if len(history) < required:
            return False
        current = history[-1]
        prior = history[-2]
        current_ma = _average([item.close for item in history[-ma_window:]])
        prior_ma = _average([item.close for item in history[-ma_window - 1:-1]])
        base_volume = _average([item.volume for item in history[-volume_window - 1:-1]])
        volume_ratio = current.volume / base_volume if base_volume else 0
        return prior.close < prior_ma and current.close >= current_ma and volume_ratio >= config["minimum_volume_ratio"]

    def exit_rule(history: tuple[DailyPrice, ...]) -> bool:
        if len(history) < ma_window:
            return False
        return history[-1].close < _average([item.close for item in history[-ma_window:]])

    return BacktestSpec(playbook.id, playbook.backtest_hypothesis, entry, exit_rule, int(config["maximum_holding_bars"]))


def build_playbook_spec(
    playbook_id: str,
    dataset: PointInTimeDataset | None = None,
) -> BacktestSpec:
    if playbook_id == "trend_core":
        return build_price_playbook_spec(playbook_id)
    if dataset is None:
        capability = describe_backtest_capability(playbook_id)
        raise ValueError(f"{playbook_id} requires a PointInTimeDataset: {', '.join(capability.required_dataset)}")
    missing = assess_dataset_coverage(playbook_id, dataset)
    if missing:
        raise ValueError(f"{playbook_id} point-in-time dataset is incomplete: {', '.join(missing)}")
    builders = {
        "hot_money_leader": _build_hot_money_leader_spec,
        "institutional_growth": _build_institutional_growth_spec,
        "institutional_value_dividend": _build_value_dividend_spec,
    }
    return builders[playbook_id](dataset)


def _build_hot_money_leader_spec(dataset: PointInTimeDataset) -> BacktestSpec:
    playbook = get_playbook("hot_money_leader")
    config = load_runtime_settings().get("backtest", "playbook_rules", playbook.id)
    trend_window = int(config["trend_window"])

    def entry(history: tuple[DailyPrice, ...]) -> bool:
        as_of = history[-1].trade_date
        market = dataset.latest_market(as_of)
        stock = dataset.latest_stock_behavior(as_of)
        if market is None or stock is None or market.available_at != as_of or stock.available_at != as_of:
            return False
        active_themes = dataset.active_themes(as_of)
        theme_rows = [dataset.latest_theme(theme, as_of) for theme in active_themes]
        valid_themes = [item for item in theme_rows if item is not None and item.available_at == as_of]
        return bool(
            market.sentiment_cycle in config["entry_sentiment_cycles"]
            and market.limit_up_count >= config["minimum_limit_up_count"]
            and market.failed_breakout_rate <= config["maximum_failed_breakout_rate"]
            and stock.limit_status in config["eligible_limit_statuses"]
            and stock.consecutive_boards <= config["maximum_consecutive_boards"]
            and stock.theme_core_rank <= config["maximum_core_rank"]
            and stock.main_net_inflow_3d >= config["minimum_main_net_inflow_3d"]
            and any(item.lifecycle in config["entry_theme_stages"] for item in valid_themes)
        )

    def exit_rule(history: tuple[DailyPrice, ...]) -> bool:
        as_of = history[-1].trade_date
        market = dataset.latest_market(as_of)
        active_themes = dataset.active_themes(as_of)
        theme_rows = [dataset.latest_theme(theme, as_of) for theme in active_themes]
        cycle_exit = market is not None and market.available_at == as_of and market.sentiment_cycle in config["exit_sentiment_cycles"]
        theme_exit = any(
            item is not None and item.available_at == as_of and item.lifecycle in config["exit_theme_stages"]
            for item in theme_rows
        )
        return cycle_exit or theme_exit or _below_moving_average(history, trend_window)

    return _point_in_time_spec(playbook.id, playbook.backtest_hypothesis, entry, exit_rule, config, dataset)


def _build_institutional_growth_spec(dataset: PointInTimeDataset) -> BacktestSpec:
    playbook = get_playbook("institutional_growth")
    config = load_runtime_settings().get("backtest", "playbook_rules", playbook.id)
    trend_window = int(config["trend_window"])

    def entry(history: tuple[DailyPrice, ...]) -> bool:
        as_of = history[-1].trade_date
        fundamental = dataset.latest_fundamental(as_of)
        consensus = dataset.latest_consensus(as_of)
        valuation = dataset.latest_valuation(as_of)
        if fundamental is None or consensus is None or valuation is None:
            return False
        return bool(
            _age_days(fundamental.announced_at, as_of) <= config["maximum_fundamental_age_days"]
            and _age_days(consensus.available_at, as_of) <= config["maximum_consensus_age_days"]
            and _age_days(valuation.available_at, as_of) <= config["maximum_valuation_age_days"]
            and fundamental.revenue_growth_yoy >= config["minimum_revenue_growth_yoy"]
            and fundamental.profit_growth_yoy >= config["minimum_profit_growth_yoy"]
            and fundamental.roe >= config["minimum_roe"]
            and fundamental.cashflow_quality is not None
            and fundamental.cashflow_quality >= config["minimum_cashflow_quality"]
            and (not config["require_positive_net_income"] or fundamental.net_income > 0)
            and (not config["require_positive_operating_cash_flow"] or fundamental.operating_cash_flow > 0)
            and not fundamental.announcement_risk
            and consensus.revision_pct >= config["minimum_consensus_revision_pct"]
            and consensus.forward_profit_growth_yoy >= config["minimum_forward_profit_growth_yoy"]
            and 0 < valuation.pe_ttm <= config["maximum_pe_ttm"]
            and _above_moving_average(history, trend_window)
        )

    def exit_rule(history: tuple[DailyPrice, ...]) -> bool:
        as_of = history[-1].trade_date
        fundamental = dataset.latest_fundamental(as_of)
        consensus = dataset.latest_consensus(as_of)
        valuation = dataset.latest_valuation(as_of)
        return bool(
            (fundamental is not None and (fundamental.announcement_risk or fundamental.profit_growth_yoy <= config["exit_profit_growth_yoy"]))
            or (consensus is not None and consensus.revision_pct <= config["exit_consensus_revision_pct"])
            or (valuation is not None and valuation.pe_ttm >= config["exit_pe_ttm"])
            or _below_moving_average(history, trend_window)
        )

    return _point_in_time_spec(playbook.id, playbook.backtest_hypothesis, entry, exit_rule, config, dataset)


def _build_value_dividend_spec(dataset: PointInTimeDataset) -> BacktestSpec:
    playbook = get_playbook("institutional_value_dividend")
    config = load_runtime_settings().get("backtest", "playbook_rules", playbook.id)
    trend_window = int(config["trend_window"])

    def entry(history: tuple[DailyPrice, ...]) -> bool:
        as_of = history[-1].trade_date
        fundamental = dataset.latest_fundamental(as_of)
        valuation = dataset.latest_valuation(as_of)
        dividend = dataset.latest_dividend(as_of)
        if fundamental is None or valuation is None or dividend is None:
            return False
        return bool(
            _age_days(fundamental.announced_at, as_of) <= config["maximum_fundamental_age_days"]
            and _age_days(valuation.available_at, as_of) <= config["maximum_valuation_age_days"]
            and _age_days(dividend.announced_at, as_of) <= config["maximum_dividend_age_days"]
            and fundamental.cashflow_quality is not None
            and fundamental.cashflow_quality >= config["minimum_cashflow_quality"]
            and fundamental.debt_to_asset <= config["maximum_debt_to_asset"]
            and fundamental.roe >= config["minimum_roe"]
            and (not config["require_positive_net_income"] or fundamental.net_income > 0)
            and (not config["require_positive_operating_cash_flow"] or fundamental.operating_cash_flow > 0)
            and (not config["require_positive_equity"] or fundamental.total_equity > 0)
            and not fundamental.announcement_risk
            and 0 < valuation.pe_ttm <= config["maximum_pe_ttm"]
            and 0 < valuation.pb <= config["maximum_pb"]
            and dividend.dividend_yield_pct >= config["minimum_dividend_yield_pct"]
            and config["minimum_payout_ratio_pct"] <= dividend.payout_ratio_pct <= config["maximum_payout_ratio_pct"]
            and _above_moving_average(history, trend_window)
        )

    def exit_rule(history: tuple[DailyPrice, ...]) -> bool:
        as_of = history[-1].trade_date
        fundamental = dataset.latest_fundamental(as_of)
        valuation = dataset.latest_valuation(as_of)
        return bool(
            (fundamental is not None and (
                fundamental.announcement_risk
                or fundamental.cashflow_quality is None
                or fundamental.cashflow_quality <= config["exit_cashflow_quality"]
                or fundamental.debt_to_asset >= config["exit_debt_to_asset"]
            ))
            or (valuation is not None and valuation.pe_ttm >= config["exit_pe_ttm"])
            or _below_moving_average(history, trend_window)
        )

    return _point_in_time_spec(playbook.id, playbook.backtest_hypothesis, entry, exit_rule, config, dataset)


def _point_in_time_spec(
    playbook_id: str,
    hypothesis: str,
    entry_rule,
    exit_rule,
    config: dict[str, object],
    dataset: PointInTimeDataset,
) -> BacktestSpec:
    return BacktestSpec(
        playbook_id,
        hypothesis,
        entry_rule,
        exit_rule,
        int(config["maximum_holding_bars"]),
        dataset_symbol=dataset.symbol,
        source_ids=tuple(dataset.source_ids()),
    )


def _above_moving_average(history: tuple[DailyPrice, ...], window: int) -> bool:
    return len(history) >= window and history[-1].close >= _average([item.close for item in history[-window:]])


def _below_moving_average(history: tuple[DailyPrice, ...], window: int) -> bool:
    return len(history) >= window and history[-1].close < _average([item.close for item in history[-window:]])


def _age_days(observed_at: str, as_of: str) -> int:
    return (date.fromisoformat(as_of) - date.fromisoformat(observed_at)).days


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0
