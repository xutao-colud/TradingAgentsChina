from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "tradingos.default.json"


@dataclass(frozen=True)
class RuntimeSettings:
    source: str
    rule_version: str
    data: dict[str, Any]

    def get(self, *path: str) -> Any:
        value: Any = self.data
        for key in path:
            if not isinstance(value, dict) or key not in value:
                raise KeyError(f"Missing runtime setting: {'.'.join(path)}")
            value = value[key]
        return value


@lru_cache(maxsize=8)
def load_runtime_settings(config_path: str | None = None) -> RuntimeSettings:
    source = Path(config_path or os.getenv("TRADINGOS_CONFIG_PATH") or DEFAULT_CONFIG_PATH)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to load TradingOS configuration from {source}: {exc}") from exc
    _validate(data)
    return RuntimeSettings(source=str(source.resolve()), rule_version=str(data["rule_version"]), data=data)


def clear_runtime_settings_cache() -> None:
    load_runtime_settings.cache_clear()


def _validate(data: object) -> None:
    if not isinstance(data, dict):
        raise RuntimeError("TradingOS configuration must be a JSON object")
    required_paths = [
        ("rule_version",), ("runtime", "network_timeout_seconds"), ("runtime", "llm_network_timeout_seconds"),
        ("runtime", "llm_request", "temperature"), ("runtime", "llm_request", "max_tokens"),
        ("runtime", "snapshot_max_workers"),
        ("providers", "eastmoney", "kline_url"), ("providers", "eastmoney", "headers"),
        ("providers", "sina", "quote_url"), ("providers", "sina", "headers"),
        ("providers", "tushare", "token_env"), ("providers", "tushare", "interfaces"),
        ("providers", "tushare", "capabilities"),
        ("providers", "tushare", "top_inst_side_codes"),
        ("providers", "tushare", "market_context"),
        ("providers", "tushare", "capital_flow_history"),
        ("providers", "tushare", "dragon_tiger_history"),
        ("providers", "tushare", "fundamental_peers"),
        ("providers", "tushare", "industry_prosperity"),
        ("providers", "tushare", "ah_premium"),
        ("providers", "akshare", "functions"), ("providers", "akshare", "capabilities"),
        ("providers", "akshare", "announcement_markets"),
        ("providers", "event_sentiment"),
        ("data_quality", "raw_snapshots"), ("data_quality", "issue_messages"),
        ("data_quality", "datasets", "daily_prices"),
        ("data_quality", "datasets", "dragon_tiger"),
        ("data_quality", "datasets", "dragon_tiger_history"),
        ("data_quality", "datasets", "announcements"),
        ("data_quality", "datasets", "margin_financing"),
        ("data_quality", "datasets", "market_sentiment"),
        ("data_quality", "datasets", "ah_premium"),
        ("data_quality", "datasets", "fundamental_peers"),
        ("data_quality", "datasets", "industry_flow"),
        ("data_quality", "datasets", "industry_valuation"),
        ("data_quality", "datasets", "northbound_holding"),
        ("data_quality", "datasets", "capital_flow_history"),
        ("providers", "models"), ("scoring", "score_bounds", "min"),
        ("scoring", "score_bounds", "max"), ("scoring", "data_readiness", "minimum_daily_bars"),
        ("scoring", "theme"),
        ("scoring", "committee_signals"),
        ("market_rules", "default_exchange"), ("market_rules", "symbol_exchange_prefixes"),
        ("market_rules", "convertible_bond_exchange_prefixes"),
        ("market_rules", "board_prefixes"), ("market_rules", "daily_limit_pct"),
        ("market_rules", "liquidity", "minimum_amount"),
        ("domain_knowledge", "theme", "lifecycle"), ("domain_knowledge", "technical"),
        ("domain_knowledge", "sentiment"),
        ("domain_knowledge", "a_share_characteristics"),
        ("domain_knowledge", "turnover_continuity"),
        ("domain_knowledge", "intraday"), ("domain_knowledge", "special_instruments"),
        ("domain_knowledge", "money_flow_tiers"), ("backtest", "commission_rate"),
        ("domain_knowledge", "capital_flow_continuity"),
        ("domain_knowledge", "dragon_tiger_depth"),
        ("domain_knowledge", "announcement_timeliness"),
        ("domain_knowledge", "industry_prosperity"),
        ("backtest", "playbook_rules", "trend_core"),
        ("backtest", "playbook_rules", "hot_money_leader"),
        ("backtest", "playbook_rules", "institutional_growth"),
        ("backtest", "playbook_rules", "institutional_value_dividend"),
    ]
    settings = RuntimeSettings(source="<validation>", rule_version=str(data.get("rule_version", "")), data=data)
    try:
        for path in required_paths:
            settings.get(*path)
    except KeyError as exc:
        raise RuntimeError(f"Invalid TradingOS configuration: {exc}") from exc
    if settings.get("scoring", "score_bounds", "min") >= settings.get("scoring", "score_bounds", "max"):
        raise RuntimeError("score_bounds.min must be below score_bounds.max")
    if settings.get("scoring", "data_readiness", "minimum_daily_bars") < 2:
        raise RuntimeError("data_readiness.minimum_daily_bars must be at least 2")
    technical = settings.get("domain_knowledge", "technical")
    required_technical_keys = {"history_bars", "moving_average_windows", "return_windows", "cost_proxy_window"}
    missing_technical_keys = sorted(required_technical_keys - set(technical))
    if missing_technical_keys:
        raise RuntimeError(f"domain_knowledge.technical misses: {', '.join(missing_technical_keys)}")
    technical_windows = [
        *technical["moving_average_windows"],
        *technical["return_windows"],
        technical["cost_proxy_window"],
    ]
    if not technical_windows or any(not isinstance(window, int) or window < 2 for window in technical_windows):
        raise RuntimeError("technical indicator windows must be integers of at least 2")
    if technical["history_bars"] < max(technical_windows):
        raise RuntimeError("technical.history_bars must cover every configured long-window indicator")
    scoring_technical = settings.get("scoring", "technical")
    scoring_ma_windows = {
        scoring_technical["ma_short"],
        scoring_technical["ma_medium"],
        scoring_technical["ma_long"],
    }
    if not scoring_ma_windows.issubset(set(technical["moving_average_windows"])):
        raise RuntimeError("technical.moving_average_windows must include every scoring MA window")
    if scoring_technical["ma_long"] not in technical["return_windows"]:
        raise RuntimeError("technical.return_windows must include scoring.technical.ma_long")
    if settings.get("data_quality", "raw_snapshots", "max_records_per_snapshot") < 1:
        raise RuntimeError("raw_snapshots.max_records_per_snapshot must be positive")
    market_context = settings.get("providers", "tushare", "market_context")
    if market_context["history_points"] < settings.get("domain_knowledge", "sentiment", "minimum_history_points"):
        raise RuntimeError("tushare.market_context.history_points cannot be below sentiment.minimum_history_points")
    if market_context["calendar_lookback_days"] < market_context["history_points"]:
        raise RuntimeError("tushare.market_context.calendar_lookback_days cannot be below history_points")
    if not market_context["one_price_first_times"]:
        raise RuntimeError("tushare.market_context.one_price_first_times cannot be empty")
    ladder_buckets = market_context["board_ladder_buckets"]
    if not ladder_buckets or any(
        not item.get("label")
        or not isinstance(item.get("minimum"), int)
        or item["minimum"] < 1
        or (item.get("maximum") is not None and item["maximum"] < item["minimum"])
        for item in ladder_buckets
    ):
        raise RuntimeError("tushare.market_context.board_ladder_buckets is invalid")
    ordered_buckets = sorted(ladder_buckets, key=lambda item: item["minimum"])
    if ordered_buckets[0]["minimum"] != 1 or any(
        current.get("maximum") is None
        or current["maximum"] + 1 != following["minimum"]
        for current, following in zip(ordered_buckets, ordered_buckets[1:])
    ) or ordered_buckets[-1].get("maximum") is not None:
        raise RuntimeError("tushare.market_context.board_ladder_buckets must continuously cover one through infinity")
    ah_premium = settings.get("providers", "tushare", "ah_premium")
    try:
        date.fromisoformat(ah_premium["available_since"])
    except (TypeError, ValueError) as exc:
        raise RuntimeError("tushare.ah_premium.available_since must be an ISO date") from exc
    if ah_premium["comparison_tolerance_pct"] < 0:
        raise RuntimeError("tushare.ah_premium.comparison_tolerance_pct cannot be negative")
    flow_history = settings.get("providers", "tushare", "capital_flow_history")
    continuity = settings.get("domain_knowledge", "capital_flow_continuity")
    if not continuity["windows"] or any(not isinstance(window, int) or window < 2 for window in continuity["windows"]):
        raise RuntimeError("capital_flow_continuity.windows must contain integers of at least 2")
    minimum_alignment = max(max(continuity["windows"]), continuity["minimum_history_points"])
    if continuity["alignment_history_points"] < minimum_alignment:
        raise RuntimeError("capital_flow_continuity.alignment_history_points cannot be below continuity requirements")
    if flow_history["history_points"] < continuity["alignment_history_points"]:
        raise RuntimeError("tushare.capital_flow_history.history_points cannot be below continuity requirements")
    if flow_history["calendar_lookback_days"] < flow_history["history_points"]:
        raise RuntimeError("tushare.capital_flow_history.calendar_lookback_days cannot be below history_points")
    dragon_history = settings.get("providers", "tushare", "dragon_tiger_history")
    dragon_depth = settings.get("domain_knowledge", "dragon_tiger_depth")
    if dragon_history["calendar_lookback_days"] < max(dragon_depth["forward_return_horizons"]):
        raise RuntimeError("tushare.dragon_tiger_history lookback cannot be below outcome horizons")
    if dragon_history["maximum_records"] < 1 or dragon_depth["minimum_history_observations"] < 1:
        raise RuntimeError("dragon-tiger history limits must be positive")
    announcement = settings.get("domain_knowledge", "announcement_timeliness")
    if not announcement["reaction_horizons"] or any(
        not isinstance(window, int) or window < 1 for window in announcement["reaction_horizons"]
    ):
        raise RuntimeError("announcement_timeliness.reaction_horizons must contain positive integers")
    if not 0 <= announcement["thread_similarity_threshold"] <= 1:
        raise RuntimeError("announcement thread similarity threshold must be between 0 and 1")
    if announcement["maximum_content_impact"] <= 0:
        raise RuntimeError("announcement maximum_content_impact must be positive")
    committee_signals = settings.get("scoring", "committee_signals")
    required_signal_keys = {
        "required_quality_status",
        "dragon_tiger",
        "margin_financing",
        "northbound_holding",
        "tiered_money_flow",
        "capital_flow_continuity",
        "industry_prosperity",
        "intraday",
        "a_share_characteristics",
        "ah_premium",
        "turnover_continuity",
    }
    missing_signal_keys = sorted(required_signal_keys - set(committee_signals))
    if missing_signal_keys:
        raise RuntimeError(f"scoring.committee_signals misses: {', '.join(missing_signal_keys)}")
    if committee_signals["required_quality_status"] != "passed":
        raise RuntimeError("committee signals must require passed semantic quality")
    if committee_signals["margin_financing"]["scale_pct"] <= 0 or committee_signals["intraday"]["imbalance_scale"] <= 0:
        raise RuntimeError("committee signal scales must be positive")
    peer_config = settings.get("providers", "tushare", "fundamental_peers")
    if peer_config["maximum_members"] < settings.get("data_quality", "datasets", "fundamental_peers", "minimum_records"):
        raise RuntimeError("tushare.fundamental_peers.maximum_members cannot be below the required sample count")
    if not peer_config["metric_fields"]:
        raise RuntimeError("tushare.fundamental_peers.metric_fields cannot be empty")
    industry_config = settings.get("providers", "tushare", "industry_prosperity")
    if industry_config["maximum_peer_members"] < industry_config["minimum_peer_samples"]:
        raise RuntimeError("tushare.industry_prosperity maximum peers cannot be below minimum samples")
    if industry_config["valuation_history_points"] < settings.get("data_quality", "datasets", "industry_valuation", "minimum_records"):
        raise RuntimeError("tushare.industry_prosperity valuation history cannot be below quality requirements")
    if industry_config["valuation_calendar_lookback_days"] < industry_config["valuation_history_points"]:
        raise RuntimeError("tushare.industry_prosperity valuation lookback is too short")
    prosperity = settings.get("domain_knowledge", "industry_prosperity")
    if prosperity["minimum_valuation_history"] < 2 or prosperity["minimum_flow_universe"] < 2:
        raise RuntimeError("industry prosperity evidence minimums must be at least two")
    valid_chain_stages = set(prosperity["supported_chain_stages"])
    if not valid_chain_stages:
        raise RuntimeError("industry prosperity must configure supported chain stages")
    for relation in industry_config["chain_relations"]:
        if (
            relation.get("stage") not in valid_chain_stages
            or not relation.get("target_industry")
            or not relation.get("industry")
            or not relation.get("source_id")
            or not relation.get("as_of")
        ):
            raise RuntimeError("industry chain relations require target, stage, industry, source_id, and as_of")
    for interface in ("stock_basic", "fina_indicator", "fina_indicator_vip", "industry_moneyflow", "ah_comparison"):
        if interface not in settings.get("providers", "tushare", "interfaces"):
            raise RuntimeError(f"tushare.interfaces misses: {interface}")
    for dataset in ("daily_prices", "dragon_tiger", "dragon_tiger_history", "announcements", "margin_financing", "market_sentiment", "ah_premium", "fundamental_peers", "industry_flow", "industry_valuation", "northbound_holding", "capital_flow_history"):
        rules = settings.get("data_quality", "datasets", dataset)
        required_rule_keys = {
            "required_fields",
            "finite_fields",
            "non_negative_fields",
            "date_field",
            "unique_fields",
            "require_analysis_date_match",
            "allow_future_date",
            "empty_status",
            "blocking",
        }
        missing_rule_keys = sorted(required_rule_keys - set(rules))
        if missing_rule_keys:
            raise RuntimeError(f"data_quality.datasets.{dataset} misses: {', '.join(missing_rule_keys)}")
        if rules["empty_status"] not in {"passed", "warning", "failed"}:
            raise RuntimeError(f"data_quality.datasets.{dataset}.empty_status is invalid")
    characteristics = settings.get("domain_knowledge", "a_share_characteristics")
    if not 0 <= characteristics["minimum_seal_rate_pct"] <= characteristics["maximum_seal_rate_pct"] <= 100:
        raise RuntimeError("a_share_characteristics seal-rate bounds are invalid")
    if characteristics["minimum_ladder_levels"] < 1:
        raise RuntimeError("a_share_characteristics.minimum_ladder_levels must be positive")
    ladder_labels = {str(item["label"]) for item in ladder_buckets}
    if not characteristics["high_board_labels"] or not set(characteristics["high_board_labels"]).issubset(ladder_labels):
        raise RuntimeError("a_share_characteristics.high_board_labels must reference configured ladder labels")
    turnover = settings.get("domain_knowledge", "turnover_continuity")
    if not turnover["windows"] or any(not isinstance(window, int) or window < 2 for window in turnover["windows"]):
        raise RuntimeError("turnover_continuity.windows must contain integers of at least two")
    if turnover["minimum_history_points"] < 2:
        raise RuntimeError("turnover_continuity.minimum_history_points must be at least two")
    if turnover["change_score_scale_pct"] <= 0:
        raise RuntimeError("turnover_continuity.change_score_scale_pct must be positive")
    playbook_rules = settings.get("backtest", "playbook_rules")
    for playbook_id in ("trend_core", "hot_money_leader", "institutional_growth", "institutional_value_dividend"):
        if not playbook_rules[playbook_id]["required_datasets"]:
            raise RuntimeError(f"backtest playbook {playbook_id} must declare required_datasets")
        if playbook_rules[playbook_id]["maximum_holding_bars"] < 1:
            raise RuntimeError(f"backtest playbook {playbook_id} maximum_holding_bars must be positive")
    for playbook_id in ("hot_money_leader", "institutional_growth", "institutional_value_dividend"):
        if playbook_rules[playbook_id]["trend_window"] < 2:
            raise RuntimeError(f"backtest playbook {playbook_id} trend_window must be at least two")
    hot_money = playbook_rules["hot_money_leader"]
    if not hot_money["entry_sentiment_cycles"] or not hot_money["entry_theme_stages"] or not hot_money["eligible_limit_statuses"]:
        raise RuntimeError("hot-money backtest must configure sentiment, theme, and stock-status filters")
    if not 0 <= hot_money["maximum_failed_breakout_rate"] <= 100:
        raise RuntimeError("hot-money maximum_failed_breakout_rate must be between zero and 100")
    if hot_money["maximum_core_rank"] < 1 or hot_money["maximum_consecutive_boards"] < 1:
        raise RuntimeError("hot-money rank and board limits must be positive")
    growth = playbook_rules["institutional_growth"]
    if min(growth["maximum_fundamental_age_days"], growth["maximum_consensus_age_days"], growth["maximum_valuation_age_days"]) < 0:
        raise RuntimeError("institutional-growth age limits cannot be negative")
    value = playbook_rules["institutional_value_dividend"]
    if min(value["maximum_fundamental_age_days"], value["maximum_dividend_age_days"], value["maximum_valuation_age_days"]) < 0:
        raise RuntimeError("value-dividend age limits cannot be negative")
    if value["minimum_payout_ratio_pct"] > value["maximum_payout_ratio_pct"]:
        raise RuntimeError("value-dividend payout ratio bounds are reversed")
