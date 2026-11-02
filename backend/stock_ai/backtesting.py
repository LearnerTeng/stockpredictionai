from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from math import isfinite, sqrt
from statistics import mean, pstdev
from typing import Any

from .features import TechnicalFeatureEngineer
from .models import StatisticalForecaster
from .strategy import RecommendationScorer, forecast_signal
from .contracts import adjusted_bars


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 10_000.0
    buy_threshold: float = 50.0
    sell_threshold: float = 38.0
    min_history: int = 35
    # Cost model: applied per executed fill, both sides.
    commission_pct: float = 0.001
    slippage_pct: float = 0.0005
    # Fill convention: signals are computed on day t's close and executed on
    # day t+1 (open by default). This removes the intraday look-ahead where a
    # signal computed from the closing price also fills at that same close.
    fill: str = "next_open"
    # When enabled, the "forecast" component of the score uses the real
    # forecaster output instead of the previous day's return as a proxy.
    use_forecaster: bool = True
    forecast_steps: int = 5
    history_window: int = 45


def _forecast_delta_pct(forecaster: StatisticalForecaster, closes: list[float], steps: int, history_window: int = 45) -> float:
    return forecast_signal(forecaster, closes, steps, history_window)[1]


def _apply_slippage(base_price: float, side: str, slippage_pct: float) -> float:
    if slippage_pct <= 0:
        return base_price
    direction = 1.0 if side == "buy" else -1.0
    return base_price * (1.0 + direction * slippage_pct)


def _annualized_sharpe(values: list[float], periods_per_year: float = 252.0) -> float | None:
    returns = [values[index] / values[index - 1] - 1.0 for index in range(1, len(values)) if values[index - 1]]
    if len(returns) < 2:
        return None
    mean_return = mean(returns)
    volatility = pstdev(returns)
    if volatility == 0:
        return None
    return (mean_return / volatility) * sqrt(periods_per_year)


def _max_drawdown_pct(values: list[float]) -> float:
    peak = float("-inf")
    max_drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        if peak:
            drawdown = (value / peak - 1.0) * 100
            max_drawdown = min(max_drawdown, drawdown)
    return max_drawdown


class ThresholdBacktester:
    """Event-driven threshold backtester with next-bar fills and a cost model.

    The signal for day t is computed from data available at day t's close and
    is executed on day t+1 at the configured reference price (default: open),
    so results do not benefit from intraday look-ahead. Commission and slippage
    are applied to every fill.
    """

    def __init__(
        self,
        feature_engineer: TechnicalFeatureEngineer | None = None,
        scorer: RecommendationScorer | None = None,
        forecaster: StatisticalForecaster | None = None,
    ):
        self.feature_engineer = feature_engineer or TechnicalFeatureEngineer()
        self.scorer = scorer or RecommendationScorer()
        self.forecaster = forecaster or StatisticalForecaster()

    def run(self, symbol: str, bars: list[dict[str, Any]], config: BacktestConfig | None = None) -> dict[str, Any]:
        cfg = config or BacktestConfig()
        if not all(isfinite(value) for value in (cfg.initial_cash, cfg.commission_pct, cfg.slippage_pct, cfg.buy_threshold, cfg.sell_threshold)):
            raise ValueError("backtest parameters must be finite")
        if cfg.initial_cash <= 0 or cfg.min_history < 2 or cfg.forecast_steps < 1 or cfg.history_window < 1:
            raise ValueError("cash and history/forecast windows must be positive")
        if cfg.slippage_pct >= 1:
            raise ValueError("slippage_pct must be less than 1")
        if cfg.commission_pct < 0 or cfg.slippage_pct < 0:
            raise ValueError("commission_pct and slippage_pct must be non-negative")
        if cfg.fill not in {"next_open", "next_close"}:
            raise ValueError("fill must be one of: next_open, next_close")

        sorted_bars = adjusted_bars(bars)
        closes = [float(bar["close"]) for bar in sorted_bars if bar.get("close") is not None]
        if len(closes) < cfg.min_history + 2:
            raise ValueError(f"{symbol} needs at least {cfg.min_history + 2} bars for backtesting")
        forecaster = deepcopy(self.forecaster)

        cash = cfg.initial_cash
        shares = 0.0
        trades: list[dict[str, Any]] = []
        equity_curve: list[dict[str, Any]] = [{
            "date": sorted_bars[cfg.min_history].get("trade_date") or sorted_bars[cfg.min_history].get("date"),
            "equity": cash, "score": None,
        }]
        total_commission = 0.0
        total_slippage_cost = 0.0
        open_trade_cost: float | None = None

        # The last bar can fill the previous signal, but cannot create a new order.
        for index in range(cfg.min_history, len(sorted_bars) - 1):
            window_closes = closes[: index + 1]
            latest_close = window_closes[-1]
            features = self.feature_engineer.build(window_closes)

            if cfg.use_forecaster:
                forecast_delta_pct = _forecast_delta_pct(forecaster, window_closes, cfg.forecast_steps, cfg.history_window)
            else:
                previous_close = window_closes[-2]
                forecast_delta_pct = (latest_close - previous_close) / previous_close * 100 if previous_close else 0.0

            score, _stance = self.scorer.score(features, forecast_delta_pct)

            current_bar = sorted_bars[index]
            next_bar = sorted_bars[index + 1]
            signal_date = current_bar.get("trade_date") or current_bar.get("date")
            fill_date = next_bar.get("trade_date") or next_bar.get("date")
            if cfg.fill == "next_open":
                base_price = float(next_bar["open"]) if next_bar.get("open") is not None else float(next_bar["close"])
            else:
                base_price = float(next_bar["close"])

            if score > cfg.buy_threshold and shares == 0:
                fill_price = _apply_slippage(base_price, "buy", cfg.slippage_pct)
                notional = cash / (1.0 + cfg.commission_pct)
                commission = notional * cfg.commission_pct
                shares = notional / fill_price
                cash = max(cash - notional - commission, 0.0)
                total_commission += commission
                total_slippage_cost += abs(fill_price - base_price) * shares
                open_trade_cost = notional + commission
                trades.append(
                    {
                        "date": fill_date,
                        "signal_date": signal_date,
                        "side": "buy",
                        "price": round(fill_price, 4),
                        "score": round(score, 2),
                        "quantity": round(shares, 6),
                        "notional": round(notional, 2),
                        "commission": round(commission, 2),
                    }
                )
            elif score < cfg.sell_threshold and shares > 0:
                fill_price = _apply_slippage(base_price, "sell", cfg.slippage_pct)
                proceeds = shares * fill_price
                commission = proceeds * cfg.commission_pct
                cash = proceeds - commission
                total_commission += commission
                total_slippage_cost += abs(fill_price - base_price) * shares
                if open_trade_cost is not None:
                    trades.append(
                        {
                            "date": fill_date,
                            "signal_date": signal_date,
                            "side": "sell",
                            "price": round(fill_price, 4),
                            "score": round(score, 2),
                            "quantity": round(shares, 6),
                            "proceeds": round(proceeds, 2),
                            "commission": round(commission, 2),
                            "round_trip_pnl_pct": round((cash / open_trade_cost - 1) * 100, 3),
                        }
                    )
                    open_trade_cost = None
                shares = 0.0

            equity = cash + shares * closes[index + 1]
            equity_curve.append({"date": fill_date, "equity": round(equity, 2), "score": round(score, 2)})

        final_equity = cash + shares * closes[-1]
        return_pct = (final_equity / cfg.initial_cash - 1) * 100
        buy_hold_return_pct = (closes[-1] / closes[cfg.min_history] - 1) * 100

        equity_values = [point["equity"] for point in equity_curve]
        closed_pnls = [trade["round_trip_pnl_pct"] for trade in trades if "round_trip_pnl_pct" in trade]
        win_rate = (sum(1 for pnl in closed_pnls if pnl > 0) / len(closed_pnls) * 100) if closed_pnls else None
        sharpe = _annualized_sharpe(equity_values)

        return {
            "symbol": symbol,
            "engine": "threshold-next-bar-v3",
            "fills": cfg.fill,
            "initial_cash": cfg.initial_cash,
            "final_equity": round(final_equity, 2),
            "return_pct": round(return_pct, 3),
            "buy_hold_return_pct": round(buy_hold_return_pct, 3),
            "excess_vs_buy_hold_pct": round(return_pct - buy_hold_return_pct, 3),
            "metrics": {
                "sharpe": round(sharpe, 3) if sharpe is not None else None,
                "max_drawdown_pct": round(_max_drawdown_pct(equity_values), 3),
                "win_rate": round(win_rate, 1) if win_rate is not None else None,
                "round_trips": len(closed_pnls),
                "open_position": shares > 0,
            },
            "costs": {
                "commission": round(total_commission, 2),
                "slippage": round(total_slippage_cost, 2),
                "total": round(total_commission + total_slippage_cost, 2),
            },
            "trades": trades,
            "equity_curve": equity_curve,
            "config": {
                "buy_threshold": cfg.buy_threshold,
                "sell_threshold": cfg.sell_threshold,
                "min_history": cfg.min_history,
                "commission_pct": cfg.commission_pct,
                "slippage_pct": cfg.slippage_pct,
                "fill": cfg.fill,
                "use_forecaster": cfg.use_forecaster,
                "forecast_steps": cfg.forecast_steps,
                "history_window": cfg.history_window,
            },
        }
