from __future__ import annotations

from dataclasses import dataclass

from app.config.runtime import load_runtime_settings
from app.schemas.report import MarketContext, MarketSentimentObservation
from app.skills.common import clamp_score


@dataclass(frozen=True)
class SentimentDynamics:
    score: int
    velocity: float | None
    acceleration: float | None
    stage: str
    observations: int
    insufficient_reason: str | None = None


def analyze_sentiment_dynamics(context: MarketContext) -> SentimentDynamics:
    config = load_runtime_settings().get("domain_knowledge", "sentiment")
    history = list(context.sentiment_history)
    if not history:
        current = _current_observation(context)
        if current is None:
            return SentimentDynamics(
                int(config["base_score"]),
                None,
                None,
                "数据不足",
                0,
                "涨跌停、炸板率或连板高度缺失，不能识别情绪周期。",
            )
        history = [current]
    scores = [_sentiment_score(item) for item in history]
    if len(scores) < config["minimum_history_points"]:
        return SentimentDynamics(scores[-1], None, None, "数据不足", len(scores), "缺少连续市场情绪观察值，不能识别启动、加速或退潮的过渡状态。")
    current = scores[-1]
    prior = scores[-2]
    baseline = sum(scores[:-1]) / len(scores[:-1])
    velocity = (current - baseline) / 100
    prior_velocity = (prior - sum(scores[:-2]) / len(scores[:-2])) / 100 if len(scores) > 2 else 0.0
    acceleration = velocity - prior_velocity
    if velocity <= config["retreat_velocity"]:
        stage = "退潮"
    elif current <= config["low_level_score"] and velocity >= config["recovery_velocity"]:
        stage = "启动"
    elif current >= config["high_level_score"] and acceleration < config["acceleration_velocity"]:
        stage = "高潮"
    elif velocity >= config["acceleration_velocity"]:
        stage = "发酵"
    elif velocity >= config["recovery_velocity"]:
        stage = "启动"
    else:
        stage = "冰点" if current <= config["low_level_score"] else "分歧"
    return SentimentDynamics(current, velocity, acceleration, stage, len(scores))


def _sentiment_score(observation: MarketSentimentObservation) -> int:
    config = load_runtime_settings().get("domain_knowledge", "sentiment")
    score = config["base_score"]
    score += observation.limit_up_count / config["limit_up_scale"]
    score -= observation.limit_down_count / config["limit_down_scale"]
    score -= observation.failed_breakout_rate * config["breakout_scale"]
    score += observation.yesterday_limit_up_premium * config["premium_scale"]
    score += observation.max_consecutive_boards * config["board_scale"]
    if observation.sealed_limit_up_rate is not None:
        score += (
            observation.sealed_limit_up_rate - config["seal_rate_neutral_pct"]
        ) * config["seal_rate_weight"]
    if observation.one_price_limit_up_count is not None:
        score += min(
            config["one_price_count_cap"],
            observation.one_price_limit_up_count * config["one_price_count_weight"],
        )
    return clamp_score(score)


def _current_observation(context: MarketContext) -> MarketSentimentObservation | None:
    required = (
        context.limit_up_count,
        context.limit_down_count,
        context.failed_breakout_rate,
        context.yesterday_limit_up_premium,
        context.max_consecutive_boards,
        context.first_board_count,
        context.second_board_success_rate,
        context.strong_stock_return,
        context.sealed_limit_up_rate,
        context.one_price_limit_up_count,
        context.broken_limit_up_count,
    )
    if any(value is None for value in required):
        return None
    return MarketSentimentObservation(
        "current",
        context.limit_up_count,
        context.limit_down_count,
        context.failed_breakout_rate,
        context.yesterday_limit_up_premium,
        context.max_consecutive_boards,
        context.first_board_count,
        context.second_board_success_rate,
        context.strong_stock_return,
        sealed_limit_up_rate=context.sealed_limit_up_rate,
        one_price_limit_up_count=context.one_price_limit_up_count,
        broken_limit_up_count=context.broken_limit_up_count,
        board_ladder=dict(context.board_ladder),
    )
