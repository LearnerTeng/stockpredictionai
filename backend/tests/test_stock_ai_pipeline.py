from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import sys
import unittest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from stock_ai.backtesting import BacktestConfig, ThresholdBacktester  # noqa: E402
from stock_ai.execution import ManualExecutionPlanner  # noqa: E402
from stock_ai.features import TechnicalFeatureEngineer  # noqa: E402
from stock_ai.models import StatisticalForecaster  # noqa: E402
from stock_ai.pipeline import PredictionRequest, StockAiPipeline  # noqa: E402
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


class FakeMarketDataProvider:
    def fetch_daily_bars(self, symbol: str, range_value: str = "1y") -> list[dict]:
        return make_bars(320)

    def fetch_prices(self, symbol: str, range_value: str = "5y") -> list[float]:
        return [float(bar["close"]) for bar in make_bars(320)]


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

    def test_pipeline_predict_returns_validation_and_model_name(self) -> None:
        pipeline = StockAiPipeline(market_data=FakeMarketDataProvider())
        result = pipeline.predict(PredictionRequest(symbol="TEST", history_window=60, forecast_steps=5))

        self.assertEqual(result["symbol"], "TEST")
        self.assertEqual(len(result["predictions"]), 5)
        self.assertIn("validation", result)
        self.assertEqual(result["validation"]["engine"], "walk-forward")
        self.assertIn(result["model"], {"statistical-trend-v1", "gradient-boosted-v1"})


class BacktesterRigorTests(unittest.TestCase):
    """P0: the backtester must not trade on the signal bar's close."""

    def make_up_then_down(self, count: int = 110) -> list[dict]:
        from datetime import date, timedelta

        bars = []
        price = 100.0
        start = date(2026, 1, 1)
        for index in range(count):
            if index < 50:
                price *= 1.015
            else:
                price *= 0.985
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

    def test_buy_fills_on_next_bar_open_not_signal_close(self) -> None:
        backtester = ThresholdBacktester()
        result = backtester.run("TEST", self.make_up_then_down())

        self.assertGreaterEqual(len(result["trades"]), 2)
        buy = result["trades"][0]
        sell = result["trades"][1]
        self.assertEqual(buy["side"], "buy")
        self.assertEqual(sell["side"], "sell")
        self.assertIn("signal_date", buy)
        self.assertNotEqual(buy["date"], buy["signal_date"])
        self.assertIn("metrics", result)
        self.assertIn("sharpe", result["metrics"])
        self.assertIn("max_drawdown_pct", result["metrics"])
        self.assertIn("costs", result)
        self.assertGreater(result["costs"]["commission"], 0)
        self.assertLessEqual(buy["notional"] + buy["commission"], result["initial_cash"] + 0.01)

    def test_zero_cost_config_has_no_cost_and_higher_equity(self) -> None:
        bars = self.make_up_then_down()
        costly = ThresholdBacktester().run("TEST", bars, BacktestConfig(commission_pct=0.01, slippage_pct=0.005))
        free = ThresholdBacktester().run("TEST", bars, BacktestConfig(commission_pct=0.0, slippage_pct=0.0))

        self.assertEqual(free["costs"]["total"], 0.0)
        self.assertGreater(free["final_equity"], costly["final_equity"])

    def test_win_rate_reported_after_round_trips(self) -> None:
        result = ThresholdBacktester().run("TEST", self.make_up_then_down())

        self.assertGreaterEqual(result["metrics"]["round_trips"], 1)
        self.assertIsNotNone(result["metrics"]["win_rate"])

    def test_forecaster_disabled_falls_back_to_momentum(self) -> None:
        bars = self.make_up_then_down()
        with_model = ThresholdBacktester().run("TEST", bars, BacktestConfig(use_forecaster=True))
        momentum = ThresholdBacktester().run("TEST", bars, BacktestConfig(use_forecaster=False))

        self.assertEqual(with_model["config"]["use_forecaster"], True)
        self.assertEqual(momentum["config"]["use_forecaster"], False)
        self.assertEqual(with_model["engine"], momentum["engine"])


if __name__ == "__main__":
    unittest.main()
