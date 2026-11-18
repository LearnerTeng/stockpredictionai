from __future__ import annotations

from math import sqrt
from statistics import mean, pstdev
from typing import Any

from .features import ema, fourier_trend, rsi, sma

FEATURE_WINDOW = 60
MIN_FEATURE_BARS = 40

FEATURE_NAMES = (
    "ret_1",
    "ret_5",
    "ret_20",
    "momentum_10",
    "rsi_14",
    "macd_hist",
    "sma_ratio_7_21",
    "ema_ratio_12_26",
    "atr_14_norm",
    "vol_20_annualized",
    "volume_z",
    "price_position",
    "fourier_strength",
)


def _returns(closes: list[float], lookback: int) -> float:
    if len(closes) <= lookback:
        return 0.0
    previous = closes[-lookback - 1]
    if not previous:
        return 0.0
    return closes[-1] / previous - 1.0


def _macd_histogram(closes: list[float]) -> float:
    """MACD histogram computed in a single pass (O(n)) instead of re-deriving
    EMAs for every prefix, which is what makes rolling feature building slow."""
    n = len(closes)
    if n < 26:
        return 0.0
    alpha_fast = 2 / 13
    alpha_slow = 2 / 27
    fast = mean(closes[:12])
    slow = mean(closes[:26])
    macd_series: list[float] = []
    for index in range(26, n):
        close = closes[index]
        fast += alpha_fast * (close - fast)
        slow += alpha_slow * (close - slow)
        macd_series.append(fast - slow)
    if not macd_series:
        return 0.0
    if len(macd_series) < 9:
        return macd_series[-1]
    alpha_signal = 2 / 10
    signal = mean(macd_series[:9])
    for value in macd_series[9:]:
        signal += alpha_signal * (value - signal)
    return macd_series[-1] - signal


def _atr_norm(bars: list[dict[str, Any]]) -> float:
    if len(bars) < 15:
        return 0.0
    true_ranges: list[float] = []
    previous_close = float(bars[0]["close"])
    for bar in bars[1:]:
        close = float(bar["close"])
        high = float(bar["high"]) if bar.get("high") is not None else max(close, previous_close)
        low = float(bar["low"]) if bar.get("low") is not None else min(close, previous_close)
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
        previous_close = close
    if not true_ranges:
        return 0.0
    atr = mean(true_ranges[-14:])
    latest_close = float(bars[-1]["close"])
    return atr / latest_close if latest_close else 0.0


def _volume_z(bars: list[dict[str, Any]]) -> float:
    volumes = [float(bar["volume"]) for bar in bars if bar.get("volume") is not None]
    if len(volumes) < 21:
        return 0.0
    recent = volumes[-21:]
    base = recent[:-1]
    volatility = pstdev(base)
    if volatility == 0:
        return 0.0
    return (recent[-1] - mean(base)) / volatility


def _price_position(closes: list[float]) -> float:
    window = closes[-min(FEATURE_WINDOW, len(closes)):]
    low = min(window)
    high = max(window)
    if high == low:
        return 0.5
    return (closes[-1] - low) / (high - low)


def build_bar_features(bars: list[dict[str, Any]]) -> dict[str, float] | None:
    """Feature vector for the most recent bar, built only from bars available
    at that point in time (no look-ahead). Returns None when there is not
    enough history to build a meaningful vector.

    Only the trailing FEATURE_WINDOW bars are used, so training hundreds of
    rolling samples stays O(n) overall instead of O(n^3).
    """
    if len(bars) < MIN_FEATURE_BARS:
        return None
    window = bars[-FEATURE_WINDOW:]
    closes = [float(bar["close"]) for bar in window]
    if len(closes) < MIN_FEATURE_BARS:
        return None

    sma_7 = sma(closes, 7)
    sma_21 = sma(closes, 21)
    ema_12 = ema(closes, 12)
    ema_26 = ema(closes, 26)
    rsi_14 = rsi(closes, 14)
    trend = fourier_trend(closes)

    recent_returns = [(curr - prev) / prev for prev, curr in zip(closes[-21:-1], closes[-20:]) if prev]
    volatility = pstdev(recent_returns) * sqrt(252) if len(recent_returns) > 2 else 0.0

    return {
        "ret_1": _returns(closes, 1),
        "ret_5": _returns(closes, 5),
        "ret_20": _returns(closes, 20),
        "momentum_10": _returns(closes, 10),
        "rsi_14": rsi_14 if rsi_14 is not None else 50.0,
        "macd_hist": _macd_histogram(closes),
        "sma_ratio_7_21": (sma_7 / sma_21 - 1.0) if sma_7 and sma_21 else 0.0,
        "ema_ratio_12_26": (ema_12 / ema_26 - 1.0) if ema_12 and ema_26 else 0.0,
        "atr_14_norm": _atr_norm(bars),
        "vol_20_annualized": volatility,
        "volume_z": _volume_z(bars),
        "price_position": _price_position(closes),
        "fourier_strength": float(trend.get("strength") or 0.0),
    }


def feature_vector(bars: list[dict[str, Any]]) -> list[float] | None:
    features = build_bar_features(bars)
    if features is None:
        return None
    return [float(features[name]) for name in FEATURE_NAMES]


def synthesize_bars_from_closes(closes: list[float]) -> list[dict[str, Any]]:
    """Minimal OHLCV bars derived from a close series so close-only consumers
    can still feed bar-based models (volume features are unavailable)."""
    bars: list[dict[str, Any]] = []
    previous_close: float | None = None
    for index, close in enumerate(closes):
        base = previous_close if previous_close is not None else close
        bars.append(
            {
                "date": f"d{index:04d}",
                "open": base,
                "high": max(base, close) * 1.005,
                "low": min(base, close) * 0.995,
                "close": close,
                "volume": None,
            }
        )
        previous_close = close
    return bars
