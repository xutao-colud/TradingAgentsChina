from __future__ import annotations

from app.schemas.report import DailyPrice


def moving_average(values: list[float], window: int) -> float | None:
    if window <= 0 or len(values) < window:
        return None
    return sum(values[-window:]) / window


def pct_change(start: float, end: float) -> float:
    if start == 0:
        return 0.0
    return (end - start) / start * 100


def volume_ratio(prices: list[DailyPrice], recent_window: int = 5, base_window: int = 20) -> float:
    if len(prices) < recent_window + 1:
        return 1.0
    recent = prices[-recent_window:]
    base = prices[-base_window:] if len(prices) >= base_window else prices
    recent_avg = sum(item.volume for item in recent) / len(recent)
    base_avg = sum(item.volume for item in base) / len(base)
    if base_avg == 0:
        return 1.0
    return recent_avg / base_avg


def trend_snapshot(prices: list[DailyPrice]) -> dict[str, float | None]:
    closes = [item.close for item in prices]
    latest = closes[-1] if closes else 0.0
    return {
        "latest_close": latest,
        "ma5": moving_average(closes, 5),
        "ma10": moving_average(closes, 10),
        "ma20": moving_average(closes, 20),
        "return_20d": pct_change(closes[-20], closes[-1]) if len(closes) >= 20 else None,
        "volume_ratio": volume_ratio(prices),
    }

