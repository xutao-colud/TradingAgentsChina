from __future__ import annotations


def clamp_score(value: float) -> int:
    bounds = load_runtime_settings().get("scoring", "score_bounds")
    return max(bounds["min"], min(bounds["max"], int(round(value))))


def average_score(scores: list[int]) -> int:
    if not scores:
        return load_runtime_settings().get("scoring", "score_bounds", "neutral")
    return clamp_score(sum(scores) / len(scores))


def confidence_from_score(score: int) -> float:
    config = load_runtime_settings().get("scoring", "confidence")
    neutral = load_runtime_settings().get("scoring", "score_bounds", "neutral")
    distance = abs(score - neutral)
    return round(min(config["maximum"], config["base"] + distance / config["distance_divisor"]), 2)
from app.config.runtime import load_runtime_settings
