from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any

from .features import FeatureSnapshot, TechnicalFeatureEngineer
from .models import StatisticalForecaster


@dataclass(frozen=True)
class ScorePolicy:
    recommendation_threshold: float = 50.0
    positive_threshold: float = 68.0
    risk_threshold: float = 38.0


class RecommendationScorer:
    def __init__(self, policy: ScorePolicy | None = None):
        self.policy = policy or ScorePolicy()

    def score(self, features: FeatureSnapshot, forecast_delta_pct: float) -> tuple[float, str]:
        score = 50.0
        if features.sma_7 is not None and features.sma_21 is not None:
            score += 12 if features.sma_7 > features.sma_21 else -12
        if features.ema_12 is not None and features.ema_26 is not None:
            score += 10 if features.ema_12 > features.ema_26 else -10
        if features.rsi_14 is not None:
            if features.rsi_14 < 35:
                score += 8
            elif features.rsi_14 > 70:
                score -= 8
        score += max(min(forecast_delta_pct, 12), -12)

        trend = features.fourier_trend
        score += 6 if trend["direction"] == "up" else -6 if trend["direction"] == "down" else 0
        score -= min(features.volatility_30d_annualized * 10, 12)
        score = min(max(score, 0), 100)

        if score >= self.policy.positive_threshold:
            stance = "watch-positive"
        elif score <= self.policy.risk_threshold:
            stance = "watch-risk"
        else:
            stance = "neutral"
        return score, stance

    def is_recommended(self, score: float) -> bool:
        return score > self.policy.recommendation_threshold


class MonitorSignalBuilder:
    def __init__(
        self,
        forecaster: StatisticalForecaster | None = None,
        feature_engineer: TechnicalFeatureEngineer | None = None,
        scorer: RecommendationScorer | None = None,
    ):
        self.forecaster = forecaster or StatisticalForecaster()
        self.feature_engineer = feature_engineer or TechnicalFeatureEngineer()
        self.scorer = scorer or RecommendationScorer()

    def build(self, symbol: str, bars: list[dict[str, Any]]) -> dict[str, Any]:
        sorted_bars = sorted(bars, key=lambda bar: bar.get("trade_date") or bar.get("date") or "")
        closes = [float(bar["close"]) for bar in sorted_bars if bar.get("close") is not None]
        if len(closes) < 30:
            raise ValueError(f"{symbol} needs at least 30 bars for monitoring")

        last_bar = sorted_bars[-1]
        latest_close = closes[-1]
        previous_close = closes[-2]
        change = latest_close - previous_close
        change_pct = (change / previous_close * 100) if previous_close else 0.0
        features = self.feature_engineer.build(closes)

        forecast_steps = 5
        forecast_window = min(45, len(closes) - forecast_steps)
        predictions = self.forecaster.forecast_series(closes[:-forecast_steps], forecast_window, forecast_steps)
        actuals = closes[-forecast_steps:]
        forecast_delta_pct = ((predictions[-1] - latest_close) / latest_close * 100) if latest_close else 0.0
        mae = mean(abs(pred - actual) for pred, actual in zip(predictions, actuals))
        score, stance = self.scorer.score(features, forecast_delta_pct)

        alerts = build_alerts(change_pct, features)

        return {
            "symbol": symbol,
            "trade_date": last_bar.get("trade_date") or last_bar.get("date"),
            "latest_close": round(latest_close, 4),
            "change": round(change, 4),
            "change_pct": round(change_pct, 4),
            "score": round(score, 2),
            "recommended": self.scorer.is_recommended(score),
            "recommendation_threshold": self.scorer.policy.recommendation_threshold,
            "stance": stance,
            "indicators": features.to_dict(),
            "forecast": {
                "steps": forecast_steps,
                "predictions": [round(value, 4) for value in predictions],
                "actuals": [round(value, 4) for value in actuals],
                "delta_pct": round(forecast_delta_pct, 4),
                "mae": round(mae, 4),
                "model": self.forecaster.name,
            },
            "alerts": alerts,
            "historical_tail": [round(value, 4) for value in closes[-60:]],
        }


def build_alerts(change_pct: float, features: FeatureSnapshot) -> list[str]:
    alerts: list[str] = []
    if abs(change_pct) >= 3:
        alerts.append(f"Daily move {change_pct:.2f}% exceeds the 3% monitor threshold.")
    if features.rsi_14 is not None and features.rsi_14 >= 70:
        alerts.append("RSI is in an overbought zone.")
    if features.rsi_14 is not None and features.rsi_14 <= 30:
        alerts.append("RSI is in an oversold zone.")
    if features.volatility_30d_annualized >= 0.45:
        alerts.append("Annualized recent volatility is elevated.")
    if not alerts:
        alerts.append("No threshold alert on the latest run.")
    return alerts
