from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import sys
import unittest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from stock_ai.backtesting import ThresholdBacktester  # noqa: E402
from stock_ai.execution import ManualExecutionPlanner  # noqa: E402
from stock_ai.features import TechnicalFeatureEngineer  # noqa: E402
from stock_ai.models import StatisticalForecaster  # noqa: E402
from stock_ai.simulation import PositionSimulationConfig, PositionSimulator  # noqa: E402
from stock_ai.strategy import MonitorSignalBuilder, RecommendationScorer  # noqa: E402


def make_bars(count: int = 80) -> list[dict]:
    bars = []
    price = 100.0
    start = date(2026, 1, 1)
    for index in range(count):
        price += 0.45 + (0.2 if index % 7 == 0 else -0.05)
        bars.append(
            {
                "date": (start + timedelta(days=index)).isoformat(),
                "close": round(price, 4),
                "open": round(price - 0.2, 4),
                "high": round(price + 0.5, 4),
                "low": round(price - 0.5, 4),
                "volume": 1_000_000 + index,
            }
        )
    return bars


class StockAiPipelineTests(unittest.TestCase):
    def test_feature_engineer_returns_expected_indicator_contract(self) -> None:
        closes = [float(bar["close"]) for bar in make_bars()]
        features = TechnicalFeatureEngineer().build(closes).to_dict()

        self.assertIn("sma_7", features)
        self.assertIn("rsi_14", features)
        self.assertIn("fourier_trend", features)
        self.assertGreater(features["sma_7"], 0)

    def test_forecaster_evaluate_returns_metrics(self) -> None:
        closes = [float(bar["close"]) for bar in make_bars()]
        result = StatisticalForecaster().evaluate(closes, history_window=30, forecast_steps=5)

        self.assertEqual(len(result.predictions), 5)
        self.assertEqual(len(result.actuals), 5)
        self.assertGreaterEqual(result.mae, 0)
        self.assertGreaterEqual(result.rmse, 0)

    def test_monitor_signal_marks_recommended_above_threshold(self) -> None:
        signal = MonitorSignalBuilder().build("TEST", make_bars())

        self.assertEqual(signal["symbol"], "TEST")
        self.assertIn("score", signal)
        self.assertEqual(signal["recommended"], signal["score"] > 50)
        self.assertEqual(signal["recommendation_threshold"], 50.0)

    def test_backtester_returns_equity_curve_and_trades(self) -> None:
        result = ThresholdBacktester().run("TEST", make_bars())

        self.assertEqual(result["symbol"], "TEST")
        self.assertGreater(len(result["equity_curve"]), 0)
        self.assertIn("return_pct", result)

    def test_position_simulator_returns_manual_and_ai_timing_scenarios(self) -> None:
        result = PositionSimulator().run(
            "TEST",
            make_bars(),
            PositionSimulationConfig(quantity=3, entry_price=120, forecast_steps=8),
        )

        self.assertEqual(result["symbol"], "TEST")
        self.assertEqual(len(result["scenarios"]), 2)
        self.assertEqual(result["scenarios"][0]["id"], "manual")
        self.assertEqual(result["scenarios"][1]["id"], "ai_timing")
        self.assertGreater(len(result["forecast_bars"]), 0)
        self.assertGreater(len(result["scenarios"][0]["points"]), 0)
        self.assertIn("assessment", result["scenarios"][0])

    def test_manual_execution_planner_never_sends_live_order(self) -> None:
        signal = {"symbol": "TEST", "recommended": True, "latest_close": 123.4, "score": 72, "stance": "watch-positive"}
        ticket = ManualExecutionPlanner().create_ticket(signal, quantity=2)

        self.assertEqual(ticket["status"], "requires_human_order")
        self.assertEqual(ticket["side"], "buy")
        self.assertIn("No live brokerage order was sent", ticket["disclaimer"])

    def test_score_policy_threshold_contract(self) -> None:
        scorer = RecommendationScorer()

        self.assertFalse(scorer.is_recommended(50.0))
        self.assertTrue(scorer.is_recommended(50.1))


if __name__ == "__main__":
    unittest.main()
