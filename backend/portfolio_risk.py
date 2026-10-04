from __future__ import annotations

from datetime import datetime, timezone
from math import sqrt
from statistics import mean, pstdev
from typing import Any

from market_data.store import MarketDataStore
from trading.store import TradingStore
from stock_ai.contracts import adjusted_price

TRADING_DAYS = 252.0
MIN_COMMON_BARS = 30
DEFAULT_WINDOW = 250


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    mean_left = mean(left)
    mean_right = mean(right)
    numerator = sum((x - mean_left) * (y - mean_right) for x, y in zip(left, right))
    denominator = sqrt(sum((x - mean_left) ** 2 for x in left) * sum((y - mean_right) ** 2 for y in right))
    if denominator == 0:
        return None
    return numerator / denominator


def _covariance(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    mean_left = mean(left)
    mean_right = mean(right)
    return sum((x - mean_left) * (y - mean_right) for x, y in zip(left, right)) / (len(left) - 1)


def _annualized_sharpe(values: list[float]) -> float | None:
    returns = [values[index] / values[index - 1] - 1.0 for index in range(1, len(values)) if values[index - 1]]
    if len(returns) < 2:
        return None
    mean_return = mean(returns)
    volatility = pstdev(returns)
    if volatility == 0:
        return None
    return (mean_return / volatility) * sqrt(TRADING_DAYS)


def _max_drawdown_pct(values: list[float]) -> float:
    peak = float("-inf")
    max_drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        if peak:
            drawdown = (value / peak - 1.0) * 100
            max_drawdown = min(max_drawdown, drawdown)
    return max_drawdown


class PortfolioRiskService:
    """Portfolio-level risk analytics: correlation, volatility, Sharpe, drawdown,
    concentration and volatility-inverse suggested weights.

    Uses whatever daily-bar history exists in the local market-data store for
    the current positions; symbols without enough history are reported as
    warnings and excluded from the matrix.
    """

    def __init__(self, market_store: MarketDataStore, trading_store: TradingStore):
        self.market_store = market_store
        self.trading_store = trading_store

    def analyze(self, window: int = DEFAULT_WINDOW, portfolio_id: str = "primary") -> dict[str, Any]:
        generated_at = datetime.now(timezone.utc).isoformat()
        portfolio = self.trading_store.get_portfolio(portfolio_id)
        positions = portfolio["positions"]
        if not positions:
            return {
                "status": "no-positions",
                "generated_at": generated_at,
                "symbols": [],
                "correlation_matrix": None,
                "portfolio": None,
                "suggested_weights": [],
                "contributions": [],
                "warnings": ["Portfolio has no open positions."],
            }

        equity = float(portfolio["equity"]) or 1.0
        series: dict[str, dict[str, float]] = {}
        warnings: list[str] = []
        for position in positions:
            symbol = position["symbol"]
            bars = self.market_store.list_daily_bars(symbol, window)
            bars = sorted(bars, key=lambda bar: bar["trade_date"])
            if len(bars) < MIN_COMMON_BARS:
                warnings.append(f"{symbol}: insufficient history ({len(bars)} bars, need {MIN_COMMON_BARS})")
                continue
            series[symbol] = {bar["trade_date"]: adjusted_price(bar) for bar in bars}

        if len(series) < 2:
            return {
                "status": "insufficient-history",
                "generated_at": generated_at,
                "symbols": sorted(series),
                "correlation_matrix": None,
                "portfolio": None,
                "suggested_weights": [],
                "contributions": [],
                "warnings": warnings + ["At least two positions with enough history are required for a correlation matrix."],
            }

        common_dates = sorted(set.intersection(*[set(dates) for dates in series.values()]))
        if len(common_dates) < MIN_COMMON_BARS:
            return {
                "status": "insufficient-history",
                "generated_at": generated_at,
                "symbols": sorted(series),
                "correlation_matrix": None,
                "portfolio": None,
                "suggested_weights": [],
                "contributions": [],
                "warnings": warnings + [f"Only {len(common_dates)} overlapping trading dates, need at least {MIN_COMMON_BARS}."],
            }

        symbols = sorted(series)
        closes = {symbol: [series[symbol][day] for day in common_dates] for symbol in symbols}
        returns = {
            symbol: [closes[symbol][index] / closes[symbol][index - 1] - 1.0 for index in range(1, len(common_dates))]
            for symbol in symbols
        }

        position_map = {position["symbol"]: position for position in positions}
        weights = {symbol: float(position_map[symbol]["market_value"]) / equity for symbol in symbols}

        correlation: list[list[float | None]] = [
            [_pearson(returns[left], returns[right]) for right in symbols] for left in symbols
        ]
        covariance: list[list[float]] = [[_covariance(returns[left], returns[right]) for right in symbols] for left in symbols]

        # Portfolio daily returns under current weights, then annualized risk.
        portfolio_returns = [
            sum(weights[left] * returns[left][index] for left in symbols) for index in range(len(returns[symbols[0]]))
        ]
        portfolio_volatility = pstdev(portfolio_returns) * sqrt(TRADING_DAYS) if len(portfolio_returns) > 1 else None

        # Marginal risk contribution: w_i * (sum_j w_j * cov_ij) / portfolio variance.
        portfolio_variance = sum(
            weights[left] * weights[right] * covariance[left_index][right_index]
            for left_index, left in enumerate(symbols)
            for right_index, right in enumerate(symbols)
        )
        variance_floor = portfolio_variance if portfolio_variance > 0 else 0.0
        contributions: list[dict[str, Any]] = []
        for index, symbol in enumerate(symbols):
            marginal = weights[symbol] * sum(
                weights[right] * covariance[index][right_index] for right_index, right in enumerate(symbols)
            )
            contribution_pct = (marginal / variance_floor * 100.0) if variance_floor > 0 else None
            contributions.append(
                {
                    "symbol": symbol,
                    "weight_pct": round(weights[symbol] * 100, 2),
                    "contribution_pct": round(contribution_pct, 2) if contribution_pct is not None else None,
                }
            )

        # Volatility-inverse allocation as a simple risk-parity starting point.
        volatilities = {symbol: pstdev(returns[symbol]) * sqrt(TRADING_DAYS) for symbol in symbols}
        inverse = {symbol: 1.0 / vol for symbol, vol in volatilities.items() if vol > 0}
        inverse_total = sum(inverse.values())
        suggested_weights = (
            [{"symbol": symbol, "weight_pct": round(inverse.get(symbol, 0) / inverse_total * 100, 2)} for symbol in symbols]
            if inverse_total > 0
            else []
        )

        hhi = sum(weight**2 for weight in weights.values())

        # Portfolio-level Sharpe and drawdown come from the persisted performance
        # curve when available.
        sharpe: float | None = None
        max_drawdown_pct: float | None = None
        try:
            performance = self.trading_store.get_performance(portfolio_id)
            values = [float(point["portfolio_value"]) for point in performance["points"]]
            if len(values) > 2:
                sharpe = _annualized_sharpe(values)
                max_drawdown_pct = _max_drawdown_pct(values)
        except ValueError:
            pass

        return {
            "status": "ok",
            "generated_at": generated_at,
            "window_days": len(common_dates),
            "price_field": "adj_close",
            "covered_equity_pct": round(sum(weights.values()) * 100, 2),
            "symbols": symbols,
            "weights": {symbol: round(weights[symbol] * 100, 2) for symbol in symbols},
            "correlation_matrix": {
                "symbols": symbols,
                "values": [[round(value, 3) if value is not None else 0.0 for value in row] for row in correlation],
            },
            "portfolio": {
                "annualized_vol_pct": round(portfolio_volatility * 100, 2) if portfolio_volatility is not None else None,
                "sharpe": round(sharpe, 2) if sharpe is not None else None,
                "max_drawdown_pct": round(max_drawdown_pct, 2) if max_drawdown_pct is not None else None,
                "hhi": round(hhi, 4),
                "effective_n": round(1.0 / hhi, 2) if hhi > 0 else None,
            },
            "suggested_weights": suggested_weights,
            "contributions": contributions,
            "warnings": warnings,
        }
