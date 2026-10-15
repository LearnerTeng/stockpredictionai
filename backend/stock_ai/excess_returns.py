from __future__ import annotations

from copy import deepcopy
from statistics import mean
from typing import Any

from .contracts import QuantObjective, adjusted_bars, adjusted_price, normalize_bars, dataset_version
from .ml_features import feature_vector

try:
    from sklearn.ensemble import HistGradientBoostingRegressor

    SKLEARN_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    HistGradientBoostingRegressor = None  # type: ignore[assignment]
    SKLEARN_AVAILABLE = False


class MultiHorizonExcessReturnForecaster:
    """Directly predicts benchmark-relative returns for each configured horizon."""

    name = "gradient-boosted-excess-return-v1"

    def __init__(
        self,
        objective: QuantObjective | None = None,
        min_train: int = 180,
        seed: int = 42,
        *,
        allow_training: bool = False,
    ):
        self.objective = objective or QuantObjective()
        self.min_train = min_train
        self.seed = seed
        self.allow_training = allow_training
        self.fitted_models: dict[int, Any] = {}
        self.training_samples: dict[int, int] = {}
        self.trained_until: str | None = None
        self.training_dataset_version: str | None = None

    def predict(self, stock_bars: list[dict[str, Any]], benchmark_bars: list[dict[str, Any]]) -> dict[str, Any]:
        stock = adjusted_bars(stock_bars)
        benchmark = normalize_bars(benchmark_bars)
        benchmark_by_date = {
            str(bar.get("trade_date") or bar.get("date")): adjusted_price(bar) for bar in benchmark
        }
        aligned = [
            bar for bar in stock if str(bar.get("trade_date") or bar.get("date")) in benchmark_by_date
        ]
        if self.fitted_models and not self.allow_training:
            return self._predict_registered(aligned, benchmark_by_date)
        if len(aligned) < self.min_train + max(self.objective.horizons) + 1:
            return self._fallback(aligned, benchmark_by_date, "insufficient-training-data")
        if not self.allow_training:
            return self._fallback(aligned, benchmark_by_date, "no-registered-model")
        if not SKLEARN_AVAILABLE or HistGradientBoostingRegressor is None:
            return self._fallback(aligned, benchmark_by_date, "scikit-learn-unavailable")

        latest_features = feature_vector(aligned)
        if latest_features is None:
            return self._fallback(aligned, benchmark_by_date, "insufficient-feature-history")

        forecasts: list[dict[str, Any]] = []
        for horizon in self.objective.horizons:
            samples: list[list[float]] = []
            labels: list[float] = []
            for index in range(40, len(aligned) - horizon):
                features = feature_vector(aligned[: index + 1])
                if features is None:
                    continue
                start = aligned[index]
                end = aligned[index + horizon]
                start_date = str(start.get("trade_date") or start.get("date"))
                end_date = str(end.get("trade_date") or end.get("date"))
                if start_date not in benchmark_by_date or end_date not in benchmark_by_date:
                    continue
                stock_return = adjusted_price(end) / adjusted_price(start) - 1.0
                benchmark_return = benchmark_by_date[end_date] / benchmark_by_date[start_date] - 1.0
                samples.append(features)
                labels.append(stock_return - benchmark_return)

            if len(samples) < self.min_train:
                return self._fallback(aligned, benchmark_by_date, f"insufficient-{horizon}d-samples")
            model = HistGradientBoostingRegressor(
                max_iter=250,
                learning_rate=0.05,
                max_depth=3,
                min_samples_leaf=20,
                l2_regularization=1.0,
                random_state=self.seed,
            )
            model.fit(samples, labels)
            self.fitted_models[horizon] = model
            self.training_samples[horizon] = len(samples)
            predicted = float(model.predict([latest_features])[0])
            training_mae = mean(abs(float(value) - float(pred)) for value, pred in zip(labels, model.predict(samples)))
            forecasts.append(
                {
                    "horizon_days": horizon,
                    "excess_return_pct": round(predicted * 100, 4),
                    "direction": "up" if predicted > 0 else "down" if predicted < 0 else "flat",
                    "training_samples": len(samples),
                    "training_mae_pct": round(training_mae * 100, 4),
                }
            )

        trained_until = str(aligned[-1].get("trade_date") or aligned[-1].get("date"))
        self.trained_until = trained_until
        self.training_dataset_version = self._dataset_version(aligned, benchmark_by_date)
        return {
            "status": "ok",
            "model_id": self.name,
            "fallback_used": False,
            "fallback_reason": None,
            "trained_until": trained_until,
            "dataset_version": self._dataset_version(aligned, benchmark_by_date),
            "objective": self.objective.to_dict(),
            "forecasts": forecasts,
        }

    def _predict_registered(self, aligned, benchmark_by_date):
        features = feature_vector(aligned)
        if features is None:
            return self._fallback(aligned, benchmark_by_date, "insufficient-feature-history")
        as_of = str(aligned[-1].get("trade_date") or aligned[-1].get("date"))
        if self.trained_until is None or as_of < self.trained_until:
            return self._fallback(aligned, benchmark_by_date, "model-trained-after-data-cutoff")
        forecasts = []
        for horizon in self.objective.horizons:
            predicted = float(self.fitted_models[horizon].predict([features])[0])
            forecasts.append({"horizon_days": horizon, "excess_return_pct": round(predicted * 100, 4),
                              "direction": "up" if predicted > 0 else "down" if predicted < 0 else "flat",
                              "training_samples": self.training_samples[horizon], "training_mae_pct": None})
        return {"status": "ok", "model_id": self.name, "fallback_used": False, "fallback_reason": None,
                "trained_until": self.trained_until, "data_cutoff": as_of,
                "training_dataset_version": self.training_dataset_version,
                "dataset_version": self._dataset_version(aligned, benchmark_by_date),
                "objective": self.objective.to_dict(), "forecasts": forecasts}

    def _fallback(
        self,
        aligned: list[dict[str, Any]],
        benchmark_by_date: dict[str, float],
        reason: str,
    ) -> dict[str, Any]:
        forecasts: list[dict[str, Any]] = []
        for horizon in self.objective.horizons:
            excess = 0.0
            if len(aligned) > horizon:
                start = aligned[-horizon - 1]
                end = aligned[-1]
                start_date = str(start.get("trade_date") or start.get("date"))
                end_date = str(end.get("trade_date") or end.get("date"))
                if start_date in benchmark_by_date and end_date in benchmark_by_date:
                    excess = (
                        adjusted_price(end) / adjusted_price(start)
                        - benchmark_by_date[end_date] / benchmark_by_date[start_date]
                    )
            forecasts.append(
                {
                    "horizon_days": horizon,
                    "excess_return_pct": round(excess * 100, 4),
                    "direction": "up" if excess > 0 else "down" if excess < 0 else "flat",
                    "training_samples": 0,
                    "training_mae_pct": None,
                }
            )
        trained_until = (
            str(aligned[-1].get("trade_date") or aligned[-1].get("date")) if aligned else None
        )
        return {
            "status": "fallback",
            "model_id": "relative-momentum-baseline-v1",
            "fallback_used": True,
            "fallback_reason": reason,
            "trained_until": trained_until,
            "dataset_version": self._dataset_version(aligned, benchmark_by_date),
            "objective": self.objective.to_dict(),
            "forecasts": forecasts,
        }

    def clone(self) -> "MultiHorizonExcessReturnForecaster":
        return deepcopy(self)

    @staticmethod
    def _dataset_version(aligned: list[dict[str, Any]], benchmark_by_date: dict[str, float]) -> str:
        return dataset_version(aligned, benchmark_by_date)
