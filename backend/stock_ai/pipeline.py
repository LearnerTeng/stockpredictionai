from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from datetime import date, datetime, timezone
import os
from pathlib import Path
from uuid import uuid4
from typing import Any

from .backtesting import ThresholdBacktester
from .contracts import adjusted_bars
from .data import EmptyNewsProvider, MarketDataProvider, NewsProvider, YahooFinanceDataProvider
from .execution import ManualExecutionPlanner
from .excess_returns import MultiHorizonExcessReturnForecaster
from .ml_models import create_forecaster
from .models import StatisticalForecaster
from .notifications import NotificationDispatcher
from .strategy import MonitorSignalBuilder, forecast_signal
from .simulation import PositionSimulationConfig, PositionSimulator
from .validation import walk_forward_evaluate


@dataclass(frozen=True)
class PredictionRequest:
    symbol: str
    history_window: int
    forecast_steps: int


class StockAiPipeline:
    def __init__(
        self,
        market_data: MarketDataProvider | None = None,
        news: NewsProvider | None = None,
        forecaster: StatisticalForecaster | None = None,
        signal_builder: MonitorSignalBuilder | None = None,
        backtester: ThresholdBacktester | None = None,
        notifications: NotificationDispatcher | None = None,
        execution: ManualExecutionPlanner | None = None,
        simulator: PositionSimulator | None = None,
    ):
        self.market_data = market_data or YahooFinanceDataProvider()
        self.news = news or EmptyNewsProvider()
        # Online requests use the deterministic baseline. Model fitting belongs
        # in a worker/CLI and registered artifacts can be injected here later.
        self.forecaster = forecaster or create_forecaster(prefer_ml=False)
        self.signal_builder = signal_builder or MonitorSignalBuilder(self.forecaster)
        self.backtester = backtester or ThresholdBacktester(forecaster=self.forecaster)
        self.notifications = notifications or NotificationDispatcher()
        self.execution = execution or ManualExecutionPlanner()
        self.simulator = simulator or PositionSimulator(self.forecaster)
        self.excess_return_forecaster = MultiHorizonExcessReturnForecaster()

    def predict(self, req: PredictionRequest) -> dict[str, Any]:
        raw_bars = self.market_data.fetch_daily_bars(req.symbol, "5y")
        bars = adjusted_bars(raw_bars)
        benchmark_error: str | None = None
        if req.symbol.upper() == "SPY":
            benchmark_bars = raw_bars
        else:
            try:
                benchmark_bars = self.market_data.fetch_daily_bars("SPY", "5y")
            except Exception as err:  # noqa: BLE001 - price prediction still remains available
                benchmark_bars = []
                benchmark_error = str(err)
        closes = [float(bar["close"]) for bar in bars]
        min_needed = req.history_window + req.forecast_steps + 20
        if len(closes) < min_needed:
            raise ValueError(
                f"Not enough data for {req.symbol}. Need at least {min_needed} daily prices, found {len(closes)}"
            )

        try:
            request_forecaster = deepcopy(self.forecaster)
            if hasattr(request_forecaster, "evaluate_from_bars"):
                forecast = request_forecaster.evaluate_from_bars(
                    bars,
                    req.forecast_steps,
                    history_window=req.history_window,
                )
            else:
                forecast = request_forecaster.evaluate(closes, req.history_window, req.forecast_steps)
        except ValueError as err:
            raise ValueError(f"Not enough data for {req.symbol}: {err}") from err

        historical_tail = closes[-min(60, len(closes)) :]
        future_predictions, future_delta = forecast_signal(deepcopy(self.forecaster), closes, req.forecast_steps, req.history_window)
        quant_forecast = self.excess_return_forecaster.predict(raw_bars, benchmark_bars)
        registry = os.getenv("MODEL_REGISTRY_DIR")
        if registry:
            from .research import registered_prediction, write_json
            try:
                quant_forecast = registered_prediction(Path(registry), req.symbol, raw_bars, benchmark_bars)
            except Exception as error:
                # A broken/missing artifact must never trigger web-side fitting.
                quant_forecast["registry_error"] = str(error)
        cutoff = quant_forecast.get("data_cutoff") or quant_forecast.get("trained_until")
        quant_forecast["data_cutoff"] = cutoff
        quant_forecast["data_stale"] = cutoff is None or not 0 <= (date.today() - date.fromisoformat(cutoff)).days <= 7
        quant_forecast["production_eligible"] = False
        if benchmark_error:
            quant_forecast["benchmark_error"] = benchmark_error
        if registry:
            write_json(Path(registry) / "predictions" / (uuid4().hex + ".json"), {
                "symbol": req.symbol, "recorded_at": datetime.now(timezone.utc).isoformat(),
                "prediction": quant_forecast,
            })
        return {
            "symbol": req.symbol,
            "history_window": req.history_window,
            "forecast_steps": req.forecast_steps,
            **forecast.to_dict(),
            "forecast_mode": "historical-holdout",
            "future_forecast": {"predictions": future_predictions, "delta_pct": future_delta,
                                "as_of": str(bars[-1].get("trade_date") or bars[-1].get("date")),
                                "reference_price": closes[-1], "price_field": "adj_close"},
            "historical_tail": [round(value, 4) for value in historical_tail],
            "model": request_forecaster.name,
            "validation": walk_forward_evaluate(request_forecaster, bars, steps=req.forecast_steps),
            "quant_forecast": quant_forecast,
        }

    def build_signal(self, symbol: str, bars: list[dict[str, Any]]) -> dict[str, Any]:
        if self.signal_builder.forecaster is self.forecaster:
            return MonitorSignalBuilder(deepcopy(self.forecaster)).build(symbol, bars)
        return self.signal_builder.build(symbol, bars)

    def backtest(self, symbol: str, bars: list[dict[str, Any]]) -> dict[str, Any]:
        return self.backtester.run(symbol, bars)

    def notify(self, signal: dict[str, Any], channel: str = "app") -> dict[str, str]:
        return self.notifications.dispatch_signal(signal, channel)

    def manual_order_ticket(self, signal: dict[str, Any], quantity: float = 1.0) -> dict[str, object]:
        return self.execution.create_ticket(signal, quantity)

    def simulate_position(
        self,
        symbol: str,
        bars: list[dict[str, Any]],
        config: PositionSimulationConfig | None = None,
    ) -> dict[str, Any]:
        return self.simulator.run(symbol, bars, config)
