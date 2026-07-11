from __future__ import annotations


def clamp_score(value: float) -> int:
    return max(0, min(100, int(round(value))))


def stage_by_score(score: int, low: str, mid: str, high: str, hot: str) -> str:
    if score >= 80:
        return hot
    if score >= 65:
        return high
    if score >= 45:
        return mid
    return low

