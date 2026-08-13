from __future__ import annotations

from dataclasses import dataclass
from math import cos, pi, sin, sqrt
from statistics import StatisticsError, linear_regression, mean, pstdev
from typing import Any


@dataclass(frozen=True)
class FeatureSnapshot:
    sma_7: float | None
    sma_21: float | None
    ema_12: float | None
    ema_26: float | None
    rsi_14: float | None
    volatility_30d_annualized: float
    fourier_trend: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "sma_7": round(self.sma_7, 4) if self.sma_7 is not None else None,
            "sma_21": round(self.sma_21, 4) if self.sma_21 is not None else None,
            "ema_12": round(self.ema_12, 4) if self.ema_12 is not None else None,
            "ema_26": round(self.ema_26, 4) if self.ema_26 is not None else None,
            "rsi_14": round(self.rsi_14, 4) if self.rsi_14 is not None else None,
            "volatility_30d_annualized": round(self.volatility_30d_annualized, 4),
            "fourier_trend": self.fourier_trend,
        }


class TechnicalFeatureEngineer:
    def build(self, closes: list[float]) -> FeatureSnapshot:
        if len(closes) < 2:
            raise ValueError("at least 2 closes are required")
        recent_returns = [
            (curr - prev) / prev
            for prev, curr in zip(closes[-31:-1], closes[-30:])
            if prev
        ]
        volatility = pstdev(recent_returns) * sqrt(252) if len(recent_returns) > 2 else 0.0
        return FeatureSnapshot(
            sma_7=sma(closes, 7),
            sma_21=sma(closes, 21),
            ema_12=ema(closes, 12),
            ema_26=ema(closes, 26),
            rsi_14=rsi(closes, 14),
            volatility_30d_annualized=volatility,
            fourier_trend=fourier_trend(closes),
        )


def sma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return mean(values[-window:])


def ema(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    alpha = 2 / (window + 1)
    ema_value = mean(values[:window])
    for value in values[window:]:
        ema_value = (value * alpha) + (ema_value * (1 - alpha))
    return ema_value


def rsi(values: list[float], window: int = 14) -> float | None:
    if len(values) <= window:
        return None
    deltas = [curr - prev for prev, curr in zip(values, values[1:])]
    recent = deltas[-window:]
    gains = [max(delta, 0.0) for delta in recent]
    losses = [abs(min(delta, 0.0)) for delta in recent]
    avg_loss = mean(losses)
    if avg_loss == 0:
        return 100.0
    rs = mean(gains) / avg_loss
    return 100 - (100 / (1 + rs))


def fourier_trend(values: list[float]) -> dict[str, Any]:
    sample = values[-min(len(values), 90) :]
    if len(sample) < 20:
        return {"direction": "flat", "strength": 0.0}

    sample_mean = mean(sample)
    detrended = [value - sample_mean for value in sample]
    n = len(detrended)
    low_frequency_scores: list[float] = []
    for frequency in (1, 2, 3):
        real = sum(value * cos(2 * pi * frequency * index / n) for index, value in enumerate(detrended))
        imag = sum(value * sin(2 * pi * frequency * index / n) for index, value in enumerate(detrended))
        low_frequency_scores.append(sqrt(real**2 + imag**2) / n)

    try:
        slope, _intercept = linear_regression(range(len(sample)), sample)
    except StatisticsError:
        slope = 0.0

    baseline = max(abs(sample_mean), 1.0)
    strength = min(abs(slope) / baseline * 1000 + sum(low_frequency_scores) / baseline, 1.0)
    direction = "up" if slope > 0 else "down" if slope < 0 else "flat"
    return {
        "direction": direction,
        "strength": round(strength, 4),
        "slope": round(slope, 6),
    }
