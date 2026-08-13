from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .features import TechnicalFeatureEngineer
from .strategy import RecommendationScorer


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 10_000.0
    buy_threshold: float = 50.0
    sell_threshold: float = 38.0
    min_history: int = 35


class ThresholdBacktester:
    """Dependency-light backtester with a Backtrader-compatible boundary.

    Backtrader can be wired in behind this class later; callers only depend on
    the run contract.
    """

    def __init__(
        self,
        feature_engineer: TechnicalFeatureEngineer | None = None,
        scorer: RecommendationScorer | None = None,
    ):
        self.feature_engineer = feature_engineer or TechnicalFeatureEngineer()
        self.scorer = scorer or RecommendationScorer()

    def run(self, symbol: str, bars: list[dict[str, Any]], config: BacktestConfig | None = None) -> dict[str, Any]:
        cfg = config or BacktestConfig()
        sorted_bars = sorted(bars, key=lambda bar: bar.get("trade_date") or bar.get("date") or "")
        closes = [float(bar["close"]) for bar in sorted_bars if bar.get("close") is not None]
        if len(closes) < cfg.min_history:
            raise ValueError(f"{symbol} needs at least {cfg.min_history} bars for backtesting")

        cash = cfg.initial_cash
        shares = 0.0
        trades: list[dict[str, Any]] = []
        equity_curve: list[dict[str, Any]] = []

        for index in range(cfg.min_history, len(sorted_bars)):
            window = closes[: index + 1]
            latest_close = window[-1]
            previous_close = window[-2]
            forecast_delta_pct = (latest_close - previous_close) / previous_close * 100 if previous_close else 0.0
            features = self.feature_engineer.build(window)
            score, _stance = self.scorer.score(features, forecast_delta_pct)

            date = sorted_bars[index].get("trade_date") or sorted_bars[index].get("date")
            if score > cfg.buy_threshold and shares == 0:
                shares = cash / latest_close
                cash = 0.0
                trades.append({"date": date, "side": "buy", "price": round(latest_close, 4), "score": round(score, 2)})
            elif score < cfg.sell_threshold and shares > 0:
                cash = shares * latest_close
                shares = 0.0
                trades.append({"date": date, "side": "sell", "price": round(latest_close, 4), "score": round(score, 2)})

            equity = cash + shares * latest_close
            equity_curve.append({"date": date, "equity": round(equity, 2), "score": round(score, 2)})

        final_equity = equity_curve[-1]["equity"]
        return_pct = (final_equity / cfg.initial_cash - 1) * 100
        buy_hold_return_pct = (closes[-1] / closes[cfg.min_history] - 1) * 100
        return {
            "symbol": symbol,
            "engine": "threshold-local",
            "initial_cash": cfg.initial_cash,
            "final_equity": final_equity,
            "return_pct": round(return_pct, 3),
            "buy_hold_return_pct": round(buy_hold_return_pct, 3),
            "trades": trades,
            "equity_curve": equity_curve,
            "config": {
                "buy_threshold": cfg.buy_threshold,
                "sell_threshold": cfg.sell_threshold,
                "min_history": cfg.min_history,
            },
        }
