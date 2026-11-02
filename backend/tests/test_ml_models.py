from __future__ import annotations

from datetime import date, timedelta
import math
from pathlib import Path
import sys
import unittest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from stock_ai.ml_models import GradientBoostedForecaster, create_forecaster  # noqa: E402
from stock_ai.models import StatisticalForecaster  # noqa: E402
from stock_ai.validation import walk_forward_evaluate  # noqa: E402


def make_bars(count: int = 400) -> list[dict]:
    bars = []
    price = 100.0
    start = date(2024, 1, 1)
    for index in range(count):
        price *= 1.001 + 0.004 * math.sin(index / 15)
        bars.append(
            {
                "date": (start + timedelta(days=index)).isoformat(),
                "open": round(price * 0.998, 4),
                "high": round(price * 1.01, 4),
                "low": round(price * 0.99, 4),
                "close": round(price, 4),
                "volume": 1_000_000 + (index * 137) % 500_000,
            }
        )
    return bars


def _sklearn_available() -> bool:
    try:
        from sklearn.ensemble import HistGradientBoostingRegressor  # noqa: F401

        return True
    except ImportError:
        return False


@unittest.skipUnless(_sklearn_available(), "scikit-learn not installed")
class MlForecasterTests(unittest.TestCase):
    def test_create_forecaster_prefers_ml(self) -> None:
        forecaster = create_forecaster(prefer_ml=True)
        self.assertEqual(forecaster.name, "gradient-boosted-v1")

    def test_fit_and_forecast_shapes(self) -> None:
        bars = make_bars()
        forecaster = GradientBoostedForecaster()
        predictions = forecaster.forecast_from_bars(bars, 5)

        self.assertEqual(len(predictions), 5)
        self.assertTrue(all(value > 0 for value in predictions))

    def test_forecaster_refits_when_bar_dataset_changes(self) -> None:
        first = make_bars()
        second = make_bars()
        for bar in second:
            bar["close"] = float(bar["close"]) * 1.5
        forecaster = GradientBoostedForecaster()
        forecaster.forecast_from_bars(first, 5)
        first_signature = forecaster._training_signature
        forecaster.forecast_from_bars(second, 5)

        self.assertNotEqual(first_signature, forecaster._training_signature)

    def test_close_only_contract_matches_forecast_series(self) -> None:
        bars = make_bars()
        closes = [float(bar["close"]) for bar in bars]
        forecaster = GradientBoostedForecaster()
        predictions = forecaster.forecast_series(closes, 60, 5)

        self.assertEqual(len(predictions), 5)
        self.assertTrue(all(value > 0 for value in predictions))

    def test_tiny_sample_falls_back_gracefully(self) -> None:
        bars = make_bars(40)
        forecaster = GradientBoostedForecaster()
        predictions = forecaster.forecast_series([float(bar["close"]) for bar in bars], 20, 3)

        self.assertEqual(len(predictions), 3)
        self.assertTrue(all(value > 0 for value in predictions))

    def test_evaluate_from_bars_returns_metrics(self) -> None:
        bars = make_bars(400)
        forecaster = GradientBoostedForecaster()
        result = forecaster.evaluate_from_bars(bars, 5)

        self.assertEqual(len(result.predictions), 5)
        self.assertEqual(len(result.actuals), 5)
        self.assertGreaterEqual(result.mae, 0)

    def test_walk_forward_reports_real_folds(self) -> None:
        bars = make_bars(400)
        validation = walk_forward_evaluate(GradientBoostedForecaster(), bars, steps=5, folds=5)

        self.assertEqual(validation["status"], "ok")
        self.assertGreaterEqual(validation["folds"], 1)
        self.assertIsNotNone(validation["mae"])
        self.assertIsNotNone(validation["direction_accuracy"])
        self.assertEqual(validation["model"], "gradient-boosted-v1")

    def test_walk_forward_statistical_model(self) -> None:
        bars = make_bars(400)
        validation = walk_forward_evaluate(StatisticalForecaster(), bars, steps=5, folds=5)

        self.assertEqual(validation["status"], "ok")
        self.assertIsNotNone(validation["rmse"])

    def test_walk_forward_insufficient_data(self) -> None:
        bars = make_bars(30)
        validation = walk_forward_evaluate(StatisticalForecaster(), bars, steps=5)

        self.assertIn(validation["status"], {"ok", "insufficient-data"})


if __name__ == "__main__":
    unittest.main()
