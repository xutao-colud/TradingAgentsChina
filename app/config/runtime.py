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
        ("rule_version",), ("runtime", "network_timeout_seconds"), ("runtime", "network_retry"), ("runtime", "llm_network_timeout_seconds"),
        ("runtime", "llm_request", "temperature"), ("runtime", "llm_request", "max_tokens"),
        ("runtime", "snapshot_max_workers"),
        ("opportunity_pipeline", "source_priority"),
        ("opportunity_pipeline", "level1"),
        ("opportunity_pipeline", "level2"),
        ("opportunity_pipeline", "level3"),
        ("opportunity_pipeline", "ranking"),
        ("opportunity_pipeline", "lifecycle"),
        ("providers", "eastmoney", "kline_url"), ("providers", "eastmoney", "headers"),
        ("providers", "high_availability", "route_order"),
        ("providers", "high_availability", "circuit_breaker"),
        ("providers", "high_availability", "verified_cache"),
        ("providers", "high_availability", "source_lag"),
        ("providers", "high_availability", "quality_summary"),
        ("providers", "public_fallback", "tencent_kline_url"),
        ("providers", "public_fallback", "sina_market_count_url"),
        ("providers", "public_fallback", "sina_market_list_url"),
        ("providers", "public_fallback", "financial_metrics"),
        ("providers", "public_fallback", "money_flow_fields"),
        ("providers", "public_fallback", "sina_tick_function"),
        ("providers", "public_fallback", "sina_tick_fields"),
        ("providers", "public_fallback", "sina_tick_direction_codes"),
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
        ("providers", "akshare", "market_context"),
        ("providers", "akshare", "bulk_snapshot_cache"),
        ("providers", "event_sentiment"),
        ("data_quality", "raw_snapshots"), ("data_quality", "issue_messages"),
        ("data_quality", "datasets", "daily_prices"),
        ("data_quality", "datasets", "dragon_tiger"),
        ("data_quality", "datasets", "dragon_tiger_history"),
        ("data_quality", "datasets", "announcements"),
        ("data_quality", "datasets", "holder_trades"),
        ("data_quality", "datasets", "pledge_risk"),
        ("data_quality", "datasets", "margin_financing"),
        ("data_quality", "datasets", "market_sentiment"),
        ("data_quality", "datasets", "market_breadth_current"),
        ("data_quality", "datasets", "ah_premium"),
        ("data_quality", "datasets", "fundamental_peers"),
        ("data_quality", "datasets", "industry_flow"),
        ("data_quality", "datasets", "industry_valuation"),
        ("data_quality", "datasets", "northbound_holding"),
        ("data_quality", "datasets", "northbound_market_flow"),
        ("data_quality", "datasets", "capital_flow_history"),
        ("providers", "models"), ("scoring", "score_bounds", "min"),
        ("scoring", "score_bounds", "max"), ("scoring", "data_readiness", "minimum_daily_bars"),
        ("scoring", "theme"),
        ("scoring", "committee_signals"),
        ("scoring", "stage_thresholds"),
        ("scoring", "market_temperature"),
        ("scoring", "money_making_effect"),
        ("scoring", "main_force_behavior"),
        ("scoring", "market_strategy_gate"),
        ("scoring", "profile_alignment"),
        ("scoring", "stock_score_model"),
        ("scoring", "evidence_chain"),
        ("scoring", "playbook_evaluator"),
        ("scoring", "committee_routing"),
        ("scoring", "research_cases"),
        ("scoring", "risk_manager"),
        ("scoring", "portfolio_manager"),
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
        ("domain_knowledge", "risk_scanner"),
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
    retry = settings.get("runtime", "network_retry")
    if retry["max_attempts"] < 1 or retry["initial_backoff_seconds"] < 0 or retry["max_backoff_seconds"] < retry["initial_backoff_seconds"]:
        raise RuntimeError("runtime.network_retry must use bounded positive attempts and backoff")
    score_min = settings.get("scoring", "score_bounds", "min")
    score_max = settings.get("scoring", "score_bounds", "max")
    opportunity = settings.get("opportunity_pipeline")
    l1 = opportunity["level1"]
    component_weights = l1["component_weights"]
    required_components = {
        "source_priority", "data_coverage", "liquidity", "capital_flow",
        "price_behavior", "profile_fit",
    }
    if required_components != set(component_weights) or abs(sum(component_weights.values()) - 1.0) > 1e-9:
        raise RuntimeError("opportunity_pipeline.level1 component weights must be complete and sum to one")
    if not 0 <= l1["minimum_data_coverage"] <= 1:
        raise RuntimeError("opportunity pipeline data coverage must be between zero and one")
    if not 0 < opportunity["level3"]["maximum_candidates"] <= opportunity["level2"]["maximum_candidates"] <= l1["maximum_candidates"] <= l1["maximum_universe"]:
        raise RuntimeError("opportunity pipeline candidate limits must satisfy L3 <= L2 <= L1 <= universe")
    if set(opportunity["source_priority"]) != {"position", "watchlist", "explicit", "radar"}:
        raise RuntimeError("opportunity pipeline source priorities are incomplete")
    if any(value < 0 for value in opportunity["source_priority"].values()):
        raise RuntimeError("opportunity pipeline source priorities cannot be negative")
    if any(l1[key] <= 0 for key in ("liquidity_full_amount", "capital_flow_ratio_full_pct", "price_change_preferred_abs_pct", "price_change_max_abs_pct")):
        raise RuntimeError("opportunity pipeline L1 scales must be positive")
    if l1["price_change_max_abs_pct"] <= l1["price_change_preferred_abs_pct"]:
        raise RuntimeError("opportunity pipeline maximum price change must exceed preferred change")
    if not l1["required_snapshot_fields"]:
        raise RuntimeError("opportunity pipeline requires at least one L1 snapshot field")
    level2 = opportunity["level2"]
    if level2["provider_fallback_price_bars"] < 2 or any(value < 1 for value in level2["summary_limits"].values()):
        raise RuntimeError("opportunity pipeline L2 fallback and summary limits must be positive")
    if not opportunity["market_blocking_statuses"]:
        raise RuntimeError("opportunity pipeline must configure market blocking statuses")
    if not opportunity["degraded_data_statuses"]:
        raise RuntimeError("opportunity pipeline must configure degraded data statuses")
    if not opportunity["admitted_radar_statuses"]:
        raise RuntimeError("opportunity pipeline must configure admitted radar statuses")
    ranking = opportunity["ranking"]
    if abs(sum(ranking.values()) - 1.0) > 1e-9:
        raise RuntimeError("opportunity pipeline ranking weights must sum to one")
    lifecycle = opportunity["lifecycle"]
    if not lifecycle["climax_score"] > lifecycle["accelerate_score"] > lifecycle["start_score"] > lifecycle["eliminate_score"]:
        raise RuntimeError("opportunity lifecycle thresholds are out of order")
    stage_thresholds = settings.get("scoring", "stage_thresholds")
    if not stage_thresholds["hot"] > stage_thresholds["high"] > stage_thresholds["mid"]:
        raise RuntimeError("stage_thresholds must satisfy hot > high > mid")
    stock_score = settings.get("scoring", "stock_score_model")
    if abs(float(stock_score["agent_weight"]) + float(stock_score["skill_weight"]) - 1.0) > 1e-9:
        raise RuntimeError("stock_score_model weights must sum to one")
    routing = settings.get("scoring", "committee_routing")
    required_factions = {"aggressive", "trend", "growth", "value", "policy", "reversal", "defensive"}
    if required_factions - set(routing["factions"]):
        raise RuntimeError("committee_routing faction configuration is incomplete")
    if routing["scaled_divisor"] <= 0 or routing["invalid_penalty_each"] < 0:
        raise RuntimeError("committee_routing divisors and penalties are invalid")
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
    breadth = settings.get("domain_knowledge", "market_breadth_confirmation")
    if breadth["top_amount_count"] < 1 or breadth["minimum_limit_balance"] < 0:
        raise RuntimeError("market breadth concentration and limit-balance settings must be non-negative")
    if not 0 <= breadth["breadth_bearish_pct"] < breadth["breadth_bullish_pct"] <= 100:
        raise RuntimeError("market breadth bullish/bearish thresholds are invalid")
    if breadth["neutral_band_pct"] < 0 or breadth["index_median_divergence_pct"] < 0:
        raise RuntimeError("market breadth divergence thresholds cannot be negative")
    if not 0 <= breadth["concentration_warning_pct"] <= 100:
        raise RuntimeError("market breadth concentration warning must be between zero and one hundred")
    if set(breadth["stages"]) != {"一致确认", "局部分化", "权重背离"} or any(
        not 0 <= float(stage["confidence_cap"]) <= 1
        for stage in breadth["stages"].values()
    ):
        raise RuntimeError("market breadth stages or confidence caps are invalid")
    if not 0 <= float(breadth["insufficient_confidence_cap"]) <= 1:
        raise RuntimeError("market breadth insufficient confidence cap must be between zero and one")
    financial_quality = settings.get("domain_knowledge", "financial_quality")
    if (
        float(financial_quality["non_recurring_warning_pct"]) <= 0
        or float(financial_quality["amount_display_divisor"]) <= 0
        or not str(financial_quality["amount_display_unit"]).strip()
    ):
        raise RuntimeError("financial quality thresholds and display units are invalid")
    public_fallback = settings.get("providers", "public_fallback")
    if not public_fallback["fundamental_quality_fields"]:
        raise RuntimeError("public fallback fundamental quality fields cannot be empty")
    if settings.get("data_quality", "raw_snapshots", "max_records_per_snapshot") < 1:
        raise RuntimeError("raw_snapshots.max_records_per_snapshot must be positive")
    if settings.get("providers", "akshare", "bulk_snapshot_cache", "maximum_age_minutes") <= 0:
        raise RuntimeError("akshare bulk snapshot cache age must be positive")
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
        "dragon_tiger_history",
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
    dragon_signal = committee_signals["dragon_tiger"]
    if dragon_signal["identified_hot_money_seat_impact"] < 0 or dragon_signal["identified_hot_money_max_impact"] < 0:
        raise RuntimeError("committee dragon-tiger seat scoring impacts cannot be negative")
    dragon_history_signal = committee_signals.get("dragon_tiger_history")
    if not isinstance(dragon_history_signal, dict):
        raise RuntimeError("scoring.committee_signals.dragon_tiger_history is required")
    if (
        dragon_history_signal["horizon_days"] not in dragon_depth["forward_return_horizons"]
        or dragon_history_signal["minimum_observations"] < dragon_depth["minimum_history_observations"]
        or not 0 <= dragon_history_signal["neutral_positive_ratio"] <= 1
        or dragon_history_signal["positive_ratio_scale"] <= 0
    ):
        raise RuntimeError("committee dragon-tiger history scoring configuration is invalid")
    continuity_signal = committee_signals["capital_flow_continuity"]
    if continuity_signal["streak_scale_days"] <= 0 or any(
        continuity_signal[key] < 0
        for key in ("aggressive_main_max_impact", "trend_margin_max_impact", "institution_northbound_max_impact")
    ):
        raise RuntimeError("committee capital-flow continuity scoring configuration is invalid")
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
    risk = settings.get("domain_knowledge", "risk_scanner")
    score_min = settings.get("scoring", "score_bounds", "min")
    score_max = settings.get("scoring", "score_bounds", "max")
    if not score_min <= risk["base_score"] <= score_max:
        raise RuntimeError("risk_scanner.base_score must stay inside score bounds")
    if any(risk[key] < 1 for key in ("holder_reduction_lookback_days", "inquiry_lookback_days", "liquidity_window_days", "minimum_liquidity_observations")):
        raise RuntimeError("risk scanner lookbacks and observation requirements must be positive")
    if risk["minimum_liquidity_observations"] > risk["liquidity_window_days"]:
        raise RuntimeError("risk scanner liquidity observations cannot exceed its window")
    if not risk["liquidity_condition_markers"]:
        raise RuntimeError("risk scanner liquidity condition markers cannot be empty")
    required_thresholds = {
        "minimum_profit_growth_yoy", "maximum_debt_to_asset_pct", "maximum_pe_ttm",
        "minimum_cashflow_quality", "maximum_goodwill_ratio_pct", "maximum_pledge_ratio_pct",
    }
    if required_thresholds - set(risk["thresholds"]):
        raise RuntimeError("risk scanner thresholds are incomplete")
    required_deductions = {
        "st", "suspended", "profit_decline", "high_debt", "high_valuation", "weak_cashflow",
        "major_shareholder_reduction", "inquiry_each", "inquiry_maximum", "high_goodwill",
        "high_pledge", "low_average_amount", "low_average_turnover", "invalid_condition",
    }
    if required_deductions - set(risk["deductions"]) or any(value < 0 for value in risk["deductions"].values()):
        raise RuntimeError("risk scanner deductions are incomplete or negative")
    grades = risk["grade_thresholds"]
    if set(grades) != {"A", "B", "C"} or not grades["A"] > grades["B"] > grades["C"] >= score_min:
        raise RuntimeError("risk scanner grade thresholds must satisfy A > B > C >= score minimum")
    for interface in ("stock_basic", "fina_indicator", "fina_indicator_vip", "pledge_stat", "industry_moneyflow", "ah_comparison", "northbound_market_flow"):
        if interface not in settings.get("providers", "tushare", "interfaces"):
            raise RuntimeError(f"tushare.interfaces misses: {interface}")
    for dataset in ("daily_prices", "dragon_tiger", "dragon_tiger_history", "announcements", "holder_trades", "pledge_risk", "margin_financing", "market_sentiment", "ah_premium", "fundamental_peers", "industry_flow", "industry_valuation", "northbound_holding", "northbound_market_flow", "capital_flow_history"):
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
    capital_scoring = settings.get("scoring", "capital")
    if capital_scoring["northbound_market_scale"] <= 0 or capital_scoring["northbound_market_max_impact"] < 0:
        raise RuntimeError("capital northbound-market scoring scale/impact is invalid")
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
