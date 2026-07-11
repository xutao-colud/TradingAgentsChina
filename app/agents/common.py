from __future__ import annotations


def clamp_score(value: float) -> int:
    return max(0, min(100, int(round(value))))


def average_score(scores: list[int]) -> int:
    if not scores:
        return 50
    return clamp_score(sum(scores) / len(scores))


def confidence_from_score(score: int) -> float:
    distance = abs(score - 50)
    return round(min(0.9, 0.52 + distance / 100), 2)

