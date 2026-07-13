from __future__ import annotations

from app.schemas.report import DailyPrice
from app.config.runtime import load_runtime_settings


def required_history_bars() -> int:
    """Return the configured number of trading bars needed by technical analysis."""
    return int(load_runtime_settings().get("domain_knowledge", "technical", "history_bars"))


def moving_average(values: list[float], window: int) -> float | None:
    if window <= 0 or len(values) < window:
        return None
    return sum(values[-window:]) / window


def pct_change(start: float, end: float) -> float:
    if start == 0:
        return 0.0
    return (end - start) / start * 100


def volume_ratio(prices: list[DailyPrice], recent_window: int, base_window: int) -> float:
    if len(prices) < recent_window + 1:
        return 1.0
    recent = prices[-recent_window:]
    base = prices[-base_window:] if len(prices) >= base_window else prices
    recent_avg = sum(item.volume for item in recent) / len(recent)
    base_avg = sum(item.volume for item in base) / len(base)
    if base_avg == 0:
        return 1.0
    return recent_avg / base_avg


def exponential_moving_average(values: list[float], window: int) -> list[float]:
    if not values or window <= 0:
        return []
    multiplier = 2 / (window + 1)
    series = [values[0]]
    for value in values[1:]:
        series.append((value - series[-1]) * multiplier + series[-1])
    return series


def macd(values: list[float], fast: int, slow: int, signal_window: int) -> tuple[float | None, float | None, float | None]:
    if len(values) < slow:
        return None, None, None
    fast_ema = exponential_moving_average(values, fast)
    slow_ema = exponential_moving_average(values, slow)
    line = [fast_value - slow_value for fast_value, slow_value in zip(fast_ema, slow_ema)]
    signal = exponential_moving_average(line, signal_window)
    histogram = (line[-1] - signal[-1]) * 2
    return line[-1], signal[-1], histogram


def bollinger(values: list[float], window: int, multiplier: float) -> tuple[float | None, float | None, float | None]:
    if len(values) < window:
        return None, None, None
    sample = values[-window:]
    middle = sum(sample) / len(sample)
    variance = sum((value - middle) ** 2 for value in sample) / len(sample)
    spread = variance ** 0.5 * multiplier
    return middle + spread, middle, middle - spread


def kdj(prices: list[DailyPrice], window: int, smoothing: int) -> tuple[float | None, float | None, float | None]:
    if len(prices) < window:
        return None, None, None
    k_value = 50.0
    d_value = 50.0
    for index in range(window - 1, len(prices)):
        segment = prices[index - window + 1:index + 1]
        highest = max(item.high for item in segment)
        lowest = min(item.low for item in segment)
        rsv = 50.0 if highest == lowest else (prices[index].close - lowest) / (highest - lowest) * 100
        k_value = (smoothing - 1) / smoothing * k_value + rsv / smoothing
        d_value = (smoothing - 1) / smoothing * d_value + k_value / smoothing
    return k_value, d_value, 3 * k_value - 2 * d_value


def cost_distribution_proxy(prices: list[DailyPrice], window: int, bins: int) -> dict[str, float | str | None]:
    if len(prices) < window:
        return {"vwap": None, "profit_volume_pct": None, "dominant_cost_zone": None}
    sample = prices[-window:]
    if not sample or sum(item.volume for item in sample) <= 0:
        return {"vwap": None, "profit_volume_pct": None, "dominant_cost_zone": None}
    total_volume = sum(item.volume for item in sample)
    vwap = sum(item.close * item.volume for item in sample) / total_volume
    profit_volume = sum(item.volume for item in sample if item.close <= sample[-1].close) / total_volume * 100
    low = min(item.low for item in sample)
    high = max(item.high for item in sample)
    if high == low:
        zone = f"{low:.2f}"
    else:
        width = (high - low) / bins
        buckets = [0.0] * bins
        for item in sample:
            index = min(bins - 1, int((item.close - low) / width))
            buckets[index] += item.volume
        index = max(range(bins), key=lambda item: buckets[item])
        zone = f"{low + index * width:.2f}-{low + (index + 1) * width:.2f}"
    return {"vwap": vwap, "profit_volume_pct": profit_volume, "dominant_cost_zone": zone}


def trend_snapshot(prices: list[DailyPrice]) -> dict[str, float | str | None]:
    technical = load_runtime_settings().get("scoring", "technical")
    config = load_runtime_settings().get("domain_knowledge", "technical")
    closes = [item.close for item in prices]
    latest = closes[-1] if closes else 0.0
    macd_line, macd_signal, macd_histogram = macd(closes, config["ema_fast"], config["ema_slow"], config["macd_signal"])
    boll_upper, boll_middle, boll_lower = bollinger(closes, config["boll_window"], config["boll_std_multiplier"])
    k_value, d_value, j_value = kdj(prices, config["kdj_window"], config["kdj_smoothing"])
    cost_proxy = cost_distribution_proxy(prices, config["cost_proxy_window"], config["cost_proxy_bins"])
    snapshot: dict[str, float | str | None] = {
        "latest_close": latest,
        "volume_ratio": volume_ratio(prices, technical["volume_recent_window"], technical["volume_base_window"]),
        "macd_line": macd_line,
        "macd_signal": macd_signal,
        "macd_histogram": macd_histogram,
        "boll_upper": boll_upper,
        "boll_middle": boll_middle,
        "boll_lower": boll_lower,
        "kdj_k": k_value,
        "kdj_d": d_value,
        "kdj_j": j_value,
        "cost_vwap": cost_proxy["vwap"],
        "cost_profit_volume_pct": cost_proxy["profit_volume_pct"],
        "cost_dominant_zone": cost_proxy["dominant_cost_zone"],
    }
    for window in config["moving_average_windows"]:
        snapshot[f"ma{window}"] = moving_average(closes, window)
    for window in config["return_windows"]:
        snapshot[f"return_{window}d"] = pct_change(closes[-window], closes[-1]) if len(closes) >= window else None
    return snapshot
