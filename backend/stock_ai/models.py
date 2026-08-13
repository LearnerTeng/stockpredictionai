from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import StatisticsError, linear_regression, mean, pstdev


@dataclass(frozen=True)
class ForecastResult:
    predictions: list[float]
    actuals: list[float]
    mae: float
    rmse: float

    def to_dict(self) -> dict[str, object]:
        return {
            "predictions": [round(value, 4) for value in self.predictions],
            "actuals": [round(value, 4) for value in self.actuals],
            "metrics": {
                "mae": round(self.mae, 4),
                "rmse": round(self.rmse, 4),
            },
        }


class StatisticalForecaster:
    """Lightweight model adapter.

    LSTM, Transformer, or FinBERT-enhanced models should implement this same
    forecast_series/evaluate contract and can then be injected into the pipeline.
    """

    name = "statistical-trend-v1"

    def predict_next(self, window: list[float]) -> float:
        if not window:
            raise ValueError("window must contain at least one value")
        if len(window) < 3:
            return float(window[-1])

        last_value = window[-1]
        avg_value = mean(window)
        deltas = [curr - prev for prev, curr in zip(window, window[1:])]
        recent_deltas = deltas[-min(8, len(deltas)) :]
        momentum = mean(recent_deltas)

        try:
            slope, intercept = linear_regression(range(len(window)), window)
            trend_estimate = slope * len(window) + intercept
        except StatisticsError:
            trend_estimate = last_value

        volatility = pstdev(recent_deltas) if len(recent_deltas) > 1 else 0.0
        mean_reversion = 0.18 * (last_value - avg_value)
        blended = (0.55 * trend_estimate) + (0.45 * (last_value + momentum)) - mean_reversion
        next_value = last_value + ((blended - last_value) * 0.82)

        if volatility:
            upper = last_value + momentum + (2.2 * volatility)
            lower = last_value + momentum - (2.2 * volatility)
            next_value = min(max(next_value, lower), upper)

        return max(next_value, 0.01)

    def forecast_series(self, series: list[float], history_window: int, forecast_steps: int) -> list[float]:
        if history_window < 1:
            raise ValueError("history_window must be positive")
        if forecast_steps < 1:
            raise ValueError("forecast_steps must be positive")
        if len(series) < history_window:
            raise ValueError("series length must be at least history_window")

        working = list(series[-history_window:])
        preds: list[float] = []
        for _ in range(forecast_steps):
            next_value = self.predict_next(working)
            preds.append(next_value)
            working = working[1:] + [next_value]
        return preds

    def evaluate(self, closes: list[float], history_window: int, forecast_steps: int) -> ForecastResult:
        min_needed = history_window + forecast_steps
        if len(closes) < min_needed:
            raise ValueError(f"need at least {min_needed} prices, found {len(closes)}")

        train_end = len(closes) - forecast_steps
        train_series = closes[:train_end]
        test_series = closes[train_end:]
        preds = self.forecast_series(train_series, history_window, forecast_steps)
        mae = mean(abs(pred - actual) for pred, actual in zip(preds, test_series))
        rmse = sqrt(mean((pred - actual) ** 2 for pred, actual in zip(preds, test_series)))
        return ForecastResult(predictions=preds, actuals=test_series, mae=mae, rmse=rmse)
