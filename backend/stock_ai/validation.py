from __future__ import annotations

from copy import deepcopy
from math import sqrt
from statistics import mean
from typing import Any


def _evaluate_fold(forecaster: Any, bars: list[dict[str, Any]], closes: list[float], cut: int, steps: int) -> dict[str, float] | None:
    train_bars = bars[:cut]
    if len(train_bars) < steps + 10:
        return None
    try:
        if hasattr(forecaster, "fit_from_bars"):
            # Walk-forward means each fold re-trains on its own expanding
            # window; otherwise later folds would reuse the first fold's model.
            forecaster.fit_from_bars(train_bars)
            predictions = forecaster.forecast_from_bars(train_bars, steps)
        elif hasattr(forecaster, "forecast_from_bars"):
            predictions = forecaster.forecast_from_bars(train_bars, steps)
        else:
            window = max(10, min(60, len(train_bars) - steps))
            predictions = forecaster.forecast_series(closes[:cut], window, steps)
    except Exception:  # noqa: BLE001 - a failing fold should not kill the whole report
        return None

    actuals = closes[cut : cut + steps]
    predictions = predictions[: len(actuals)]
    if not actuals or len(predictions) != len(actuals):
        return None

    mae = mean(abs(pred - actual) for pred, actual in zip(predictions, actuals))
    rmse = sqrt(mean((pred - actual) ** 2 for pred, actual in zip(predictions, actuals)))
    start_close = closes[cut - 1]
    predicted_direction = 1 if predictions[-1] > start_close else -1 if predictions[-1] < start_close else 0
    actual_direction = 1 if actuals[-1] > start_close else -1 if actuals[-1] < start_close else 0
    direction_accuracy = 1.0 if predicted_direction == actual_direction else 0.0
    return {"mae": mae, "rmse": rmse, "direction_accuracy": direction_accuracy}


def walk_forward_evaluate(
    forecaster: Any,
    bars: list[dict[str, Any]],
    *,
    steps: int = 5,
    folds: int = 5,
    min_train: int = 120,
) -> dict[str, Any]:
    """Rolling window validation with expanding training sets.

    Unlike a single end-of-series holdout, this walks the training window
    forward and aggregates errors over multiple out-of-sample folds, so the
    reported MAE/RMSE has real statistical meaning. Works with any forecaster
    exposing ``forecast_from_bars(bars, steps)`` (or the closes-based
    ``forecast_series`` fallback).
    """
    if steps < 1:
        raise ValueError("steps must be positive")
    closes = [float(bar["close"]) for bar in bars]
    n = len(closes)
    if n < min_train + steps:
        min_train = max(60, steps * 2)
    # Models with their own training requirement (e.g. the gradient-boosted
    # forecaster) need a larger expanding window or every fold silently falls
    # back to the statistical model. Doubling the model's minimum guarantees
    # the earliest fold still has enough samples to train the real model.
    model_min_train = int(getattr(forecaster, "min_train", 0) or 0)
    min_train = max(min_train, model_min_train * 2)
    available = n - min_train - steps

    fold_results: list[dict[str, float]] = []
    attempted_folds = 0
    if available < steps:
        attempted_folds += 1
        fold = _evaluate_fold(deepcopy(forecaster), bars, closes, n - steps, steps)
        if fold is not None:
            fold_results.append(fold)
    else:
        step_size = max(steps, 1)
        last_cut = n - steps
        fold_count = max(1, min(folds, (last_cut - min_train) // step_size))
        if fold_count == 1:
            cuts = [last_cut]
        else:
            cuts = sorted(
                {
                    min_train + round(index * (last_cut - min_train) / (fold_count - 1))
                    for index in range(fold_count)
                }
            )
        for cut in cuts:
            attempted_folds += 1
            fold = _evaluate_fold(deepcopy(forecaster), bars, closes, cut, steps)
            if fold is not None:
                fold_results.append(fold)

    if not fold_results:
        return {
            "engine": "walk-forward",
            "status": "insufficient-data",
            "folds": 0,
            "attempted_folds": attempted_folds,
            "failed_folds": attempted_folds,
            "steps": steps,
            "min_train": min_train,
            "mae": None,
            "rmse": None,
            "direction_accuracy": None,
            "model": getattr(forecaster, "name", "unknown"),
        }

    return {
        "engine": "walk-forward",
        "status": "ok",
        "folds": len(fold_results),
        "attempted_folds": attempted_folds,
        "failed_folds": attempted_folds - len(fold_results),
        "steps": steps,
        "min_train": min_train,
        "mae": round(mean(fold["mae"] for fold in fold_results), 4),
        "rmse": round(mean(fold["rmse"] for fold in fold_results), 4),
        "direction_accuracy": round(mean(fold["direction_accuracy"] for fold in fold_results), 4),
        "model": getattr(forecaster, "name", "unknown"),
    }
