from __future__ import annotations

from datetime import date, timedelta
from hashlib import sha256
from math import sqrt
from statistics import mean
from typing import Any

from .ml_features import feature_vector, synthesize_bars_from_closes
from .models import ForecastResult, StatisticalForecaster

try:
    # Imported eagerly (but guarded) so the one-time sklearn module cost is
    # paid at process startup instead of on the first model fit.
    from sklearn.ensemble import HistGradientBoostingRegressor as _HistGradientBoostingRegressor

    _SKLEARN_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised when ML deps are absent
    _HistGradientBoostingRegressor = None  # type: ignore[assignment]
    _SKLEARN_AVAILABLE = False


def _sklearn_regressor(seed: int):
    if _HistGradientBoostingRegressor is None:
        raise ImportError("scikit-learn is not installed")
    return _HistGradientBoostingRegressor(
        max_iter=250,
        learning_rate=0.05,
        max_depth=3,
        min_samples_leaf=20,
        l2_regularization=1.0,
        random_state=seed,
    )


def _next_trading_day(value: Any) -> str:
    try:
        current = date.fromisoformat(str(value))
    except ValueError:
        return f"proj{value}"
    next_day = current + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    return next_day.isoformat()


class GradientBoostedForecaster:
    """Optional machine-learning forecaster with the same contract as
    StatisticalForecaster.

    Trains a gradient-boosted tree on bar-derived features (technical
    indicators, volatility, volume flow) to predict the next-bar return, then
    compounds predictions recursively for multi-step forecasts. Requires
    scikit-learn; every public method degrades to the statistical forecaster
    when scikit-learn is unavailable or when the training sample is too small,
    so callers never need a try/except.

    ``horizon`` records the conventional forecast length used by callers and
    is not part of the training labels.
    """

    name = "gradient-boosted-v1"

    def __init__(self, horizon: int = 5, min_train: int = 120, seed: int = 42):
        if horizon < 1:
            raise ValueError("horizon must be positive")
        self.horizon = horizon
        self.min_train = min_train
        self.seed = seed
        self._model = None
        self._training_signature: str | None = None
        self._fallback = StatisticalForecaster()

    # -- training ---------------------------------------------------------

    def fit_from_bars(self, bars: list[dict[str, Any]]) -> "GradientBoostedForecaster":
        closes = [float(bar["close"]) for bar in bars]
        usable = len(closes) - 1
        if usable <= self.min_train:
            raise ValueError(f"need at least {self.min_train + 1} bars to train, found {len(closes)}")

        samples: list[list[float]] = []
        targets: list[float] = []
        for index in range(self.min_train, usable):
            vector = feature_vector(bars[: index + 1])
            if vector is None:
                continue
            samples.append(vector)
            # One-bar forward return: inference applies one prediction per
            # step and compounds recursively, so the label must match a single
            # step rather than the full forecast horizon.
            targets.append(closes[index + 1] / closes[index] - 1.0)
        if len(samples) < 60:
            raise ValueError("not enough training samples after feature building")

        model = _sklearn_regressor(self.seed)
        model.fit(samples, targets)
        self._model = model
        self._training_signature = self._bars_signature(bars)
        return self

    def _predict_next(self, bars: list[dict[str, Any]]) -> float:
        vector = feature_vector(bars)
        latest_close = float(bars[-1]["close"])
        if vector is None or self._model is None:
            return latest_close
        predicted_return = float(self._model.predict([vector])[0])
        return max(latest_close * (1.0 + predicted_return), 0.01)

    # -- forecasting ------------------------------------------------------

    def forecast_from_bars(self, bars: list[dict[str, Any]], steps: int) -> list[float]:
        if steps < 1:
            raise ValueError("steps must be positive")
        if self._model is None or self._training_signature != self._bars_signature(bars):
            try:
                self.fit_from_bars(bars)
            except (ImportError, ValueError):
                return self._fallback.forecast_from_bars(bars, steps)

        working = list(bars)
        predictions: list[float] = []
        for _ in range(steps):
            predicted = self._predict_next(working)
            predictions.append(predicted)
            last_close = float(working[-1]["close"])
            working.append(
                {
                    "date": _next_trading_day(working[-1].get("date") or "d0000"),
                    "open": last_close,
                    "high": max(last_close, predicted) * 1.005,
                    "low": min(last_close, predicted) * 0.995,
                    "close": predicted,
                    "volume": None,
                }
            )
        return predictions

    @staticmethod
    def _bars_signature(bars: list[dict[str, Any]]) -> str:
        digest = sha256()
        for bar in bars:
            digest.update(str(bar.get("trade_date") or bar.get("date") or "").encode("ascii", "ignore"))
            digest.update(f"|{float(bar['close']):.8f};".encode("ascii"))
        return digest.hexdigest()

    def forecast_series(self, series: list[float], history_window: int, forecast_steps: int) -> list[float]:
        return self.forecast_from_bars(synthesize_bars_from_closes(series), forecast_steps)

    # -- evaluation -------------------------------------------------------

    def evaluate_from_bars(self, bars: list[dict[str, Any]], steps: int, *, history_window: int | None = None) -> ForecastResult:
        closes = [float(bar["close"]) for bar in bars]
        if len(closes) < self.min_train + steps:
            raise ValueError(f"need at least {self.min_train + steps} prices, found {len(closes)}")
        train = bars[: len(bars) - steps]
        predictions = self.forecast_from_bars(train, steps)
        actuals = closes[-steps:]
        predictions = predictions[: len(actuals)]
        mae = mean(abs(pred - actual) for pred, actual in zip(predictions, actuals))
        rmse = sqrt(mean((pred - actual) ** 2 for pred, actual in zip(predictions, actuals)))
        return ForecastResult(predictions=predictions, actuals=actuals, mae=mae, rmse=rmse)

    def evaluate(self, closes: list[float], history_window: int, forecast_steps: int) -> ForecastResult:
        return self.evaluate_from_bars(synthesize_bars_from_closes(closes), forecast_steps)


def create_forecaster(prefer_ml: bool = True) -> StatisticalForecaster | GradientBoostedForecaster:
    """Return the best available forecaster. Falls back to the deterministic
    statistical model when scikit-learn is not installed."""
    if prefer_ml and _SKLEARN_AVAILABLE:
        return GradientBoostedForecaster()
    return StatisticalForecaster()
