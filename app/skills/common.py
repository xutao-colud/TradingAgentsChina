from __future__ import annotations

from app.config.runtime import load_runtime_settings


def clamp_score(value: float) -> int:
    bounds = load_runtime_settings().get("scoring", "score_bounds")
    return max(int(bounds["min"]), min(int(bounds["max"]), int(round(value))))


def stage_by_score(score: int, low: str, mid: str, high: str, hot: str) -> str:
    thresholds = load_runtime_settings().get("scoring", "stage_thresholds")
    if score >= int(thresholds["hot"]):
        return hot
    if score >= int(thresholds["high"]):
        return high
    if score >= int(thresholds["mid"]):
        return mid
    return low
