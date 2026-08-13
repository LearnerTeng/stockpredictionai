from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .backtesting import ThresholdBacktester
from .data import EmptyNewsProvider, MarketDataProvider, NewsProvider, YahooFinanceDataProvider
from .execution import ManualExecutionPlanner
from .models import StatisticalForecaster
from .notifications import NotificationDispatcher
from .strategy import MonitorSignalBuilder
from .simulation import PositionSimulationConfig, PositionSimulator


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
        self.forecaster = forecaster or StatisticalForecaster()
        self.signal_builder = signal_builder or MonitorSignalBuilder(self.forecaster)
        self.backtester = backtester or ThresholdBacktester()
        self.notifications = notifications or NotificationDispatcher()
        self.execution = execution or ManualExecutionPlanner()
        self.simulator = simulator or PositionSimulator(self.forecaster)

    def predict(self, req: PredictionRequest) -> dict[str, Any]:
        closes = self.market_data.fetch_prices(req.symbol)
        min_needed = req.history_window + req.forecast_steps + 20
        if len(closes) < min_needed:
            raise ValueError(
                f"Not enough data for {req.symbol}. Need at least {min_needed} daily prices, found {len(closes)}"
            )

        forecast = self.forecaster.evaluate(closes, req.history_window, req.forecast_steps)
        historical_tail = closes[-min(60, len(closes)) :]
        return {
            "symbol": req.symbol,
            "history_window": req.history_window,
            "forecast_steps": req.forecast_steps,
            **forecast.to_dict(),
            "historical_tail": [round(value, 4) for value in historical_tail],
            "model": self.forecaster.name,
        }

    def build_signal(self, symbol: str, bars: list[dict[str, Any]]) -> dict[str, Any]:
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
