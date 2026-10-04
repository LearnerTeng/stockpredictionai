from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from .features import TechnicalFeatureEngineer
from .models import StatisticalForecaster
from .strategy import RecommendationScorer


@dataclass(frozen=True)
class PositionSimulationConfig:
    quantity: float = 1.0
    entry_price: float | None = None
    entry_date: str | None = None
    forecast_steps: int = 20
    history_window: int = 60
    ai_lookback: int = 90


class PositionSimulator:
    def __init__(
        self,
        forecaster: StatisticalForecaster | None = None,
        feature_engineer: TechnicalFeatureEngineer | None = None,
        scorer: RecommendationScorer | None = None,
    ):
        self.forecaster = forecaster or StatisticalForecaster()
        self.feature_engineer = feature_engineer or TechnicalFeatureEngineer()
        self.scorer = scorer or RecommendationScorer()

    def run(self, symbol: str, bars: list[dict[str, Any]], config: PositionSimulationConfig | None = None) -> dict[str, Any]:
        cfg = config or PositionSimulationConfig()
        if cfg.quantity <= 0:
            raise ValueError("quantity must be greater than 0")
        if cfg.forecast_steps < 1 or cfg.forecast_steps > 60:
            raise ValueError("forecast_steps must be between 1 and 60")

        sorted_bars = sorted(bars, key=lambda bar: bar.get("trade_date") or bar.get("date") or "")
        closes = [float(bar["close"]) for bar in sorted_bars if bar.get("close") is not None]
        if len(closes) < 35:
            raise ValueError(f"{symbol} needs at least 35 bars for position simulation")

        latest_bar = _normalize_bar(sorted_bars[-1], symbol)
        latest_close = latest_bar["close"]
        manual_entry_date = cfg.entry_date or latest_bar["trade_date"]
        manual_entry_price = float(cfg.entry_price) if cfg.entry_price is not None else latest_close
        if manual_entry_price <= 0:
            raise ValueError("entry_price must be greater than 0")

        ai_entry = self._select_ai_entry(symbol, sorted_bars, closes, cfg.ai_lookback)
        forecast_bars = _build_projected_bars(
            symbol=symbol,
            last_bar=latest_bar,
            predictions=self.forecaster.forecast_series(
                closes,
                min(cfg.history_window, len(closes)),
                cfg.forecast_steps,
            ),
        )
        normalized_actual = [_normalize_bar(bar, symbol, projected=False) for bar in sorted_bars]

        return {
            "symbol": symbol,
            "latest_bar": latest_bar,
            "forecast_bars": forecast_bars,
            "ai_entry": ai_entry,
            "scenarios": [
                _build_scenario(
                    scenario_id="manual",
                    label="Manual entry",
                    quantity=cfg.quantity,
                    entry_date=manual_entry_date,
                    entry_price=manual_entry_price,
                    actual_bars=normalized_actual,
                    forecast_bars=forecast_bars,
                ),
                _build_scenario(
                    scenario_id="ai_timing",
                    label="AI timing entry",
                    quantity=cfg.quantity,
                    entry_date=ai_entry["trade_date"],
                    entry_price=ai_entry["price"],
                    actual_bars=normalized_actual,
                    forecast_bars=forecast_bars,
                ),
            ],
            "engine": {
                "forecast_model": self.forecaster.name,
                "signal_model": "deterministic-score-v1",
                "forecast_steps": cfg.forecast_steps,
            },
            "disclaimer": "Paper simulation only. Projected bars are model output, not live market data or investment advice.",
        }

    def _select_ai_entry(
        self,
        symbol: str,
        sorted_bars: list[dict[str, Any]],
        closes: list[float],
        lookback: int,
    ) -> dict[str, Any]:
        min_history = 35
        start_index = max(min_history, len(sorted_bars) - max(lookback, min_history))
        best: dict[str, Any] | None = None
        first_recommended: dict[str, Any] | None = None

        for index in range(start_index, len(sorted_bars)):
            window = closes[: index + 1]
            latest_close = window[-1]
            previous_close = window[-2]
            forecast_delta_pct = ((latest_close - previous_close) / previous_close * 100) if previous_close else 0.0
            features = self.feature_engineer.build(window)
            score, stance = self.scorer.score(features, forecast_delta_pct)
            trade_date = sorted_bars[index].get("trade_date") or sorted_bars[index].get("date")
            candidate = {
                "symbol": symbol,
                "trade_date": trade_date,
                "price": round(latest_close, 4),
                "score": round(score, 2),
                "stance": stance,
                "reason": _entry_reason(score, stance),
            }
            if first_recommended is None and self.scorer.is_recommended(score):
                first_recommended = candidate
            if best is None or score > best["score"]:
                best = candidate

        selected = first_recommended or best
        if selected is None:
            latest = _normalize_bar(sorted_bars[-1], symbol)
            selected = {
                "symbol": symbol,
                "trade_date": latest["trade_date"],
                "price": latest["close"],
                "score": 0.0,
                "stance": "neutral",
                "reason": "Not enough signal history; fallback uses the latest close.",
            }
        return selected


def _entry_reason(score: float, stance: str) -> str:
    if score > 68:
        return "Score crossed the positive watch threshold with constructive trend and risk balance."
    if score > 50:
        return "Score moved above the recommendation threshold; suitable for watchlist simulation."
    return f"Best available timing in the recent window, but stance remains {stance}."


def _normalize_bar(bar: dict[str, Any], symbol: str, projected: bool = False) -> dict[str, Any]:
    close = float(bar["close"])
    open_price = float(bar["open"]) if bar.get("open") is not None else close
    high = float(bar["high"]) if bar.get("high") is not None else max(open_price, close)
    low = float(bar["low"]) if bar.get("low") is not None else min(open_price, close)
    return {
        "symbol": str(bar.get("symbol") or symbol).upper(),
        "trade_date": str(bar.get("trade_date") or bar.get("date")),
        "open": round(open_price, 4),
        "high": round(max(high, open_price, close), 4),
        "low": round(min(low, open_price, close), 4),
        "close": round(close, 4),
        "volume": int(bar["volume"]) if bar.get("volume") is not None else None,
        "projected": projected,
    }


def _build_projected_bars(symbol: str, last_bar: dict[str, Any], predictions: list[float]) -> list[dict[str, Any]]:
    bars: list[dict[str, Any]] = []
    previous_close = float(last_bar["close"])
    current_date = date.fromisoformat(last_bar["trade_date"])
    for prediction in predictions:
        current_date = _next_trading_day(current_date)
        close = max(float(prediction), 0.01)
        high = max(previous_close, close) * 1.006
        low = min(previous_close, close) * 0.994
        bars.append(
            {
                "symbol": symbol,
                "trade_date": current_date.isoformat(),
                "open": round(previous_close, 4),
                "high": round(high, 4),
                "low": round(low, 4),
                "close": round(close, 4),
                "volume": None,
                "projected": True,
            }
        )
        previous_close = close
    return bars


def _next_trading_day(value: date) -> date:
    next_day = value + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    return next_day


def _build_scenario(
    *,
    scenario_id: str,
    label: str,
    quantity: float,
    entry_date: str,
    entry_price: float,
    actual_bars: list[dict[str, Any]],
    forecast_bars: list[dict[str, Any]],
) -> dict[str, Any]:
    timeline = [bar for bar in actual_bars if bar["trade_date"] >= entry_date]
    if not timeline:
        timeline = [actual_bars[-1]]
    if timeline[-1]["trade_date"] != forecast_bars[0]["trade_date"]:
        timeline = timeline + forecast_bars
    else:
        timeline = timeline + forecast_bars[1:]

    cost_basis = quantity * entry_price
    points: list[dict[str, Any]] = []
    peak_value = cost_basis
    max_drawdown_pct = 0.0
    for bar in timeline:
        value = quantity * float(bar["close"])
        pnl = value - cost_basis
        pnl_pct = (pnl / cost_basis * 100) if cost_basis else 0.0
        peak_value = max(peak_value, value)
        drawdown_pct = ((value / peak_value) - 1) * 100 if peak_value else 0.0
        max_drawdown_pct = min(max_drawdown_pct, drawdown_pct)
        points.append(
            {
                "trade_date": bar["trade_date"],
                "close": bar["close"],
                "value": round(value, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 3),
                "projected": bool(bar.get("projected")),
            }
        )

    current_point = points[-1]
    return {
        "id": scenario_id,
        "label": label,
        "quantity": quantity,
        "entry_date": entry_date,
        "entry_price": round(entry_price, 4),
        "cost_basis": round(cost_basis, 2),
        "latest_value": current_point["value"],
        "pnl": current_point["pnl"],
        "pnl_pct": current_point["pnl_pct"],
        "max_drawdown_pct": round(max_drawdown_pct, 3),
        "points": points,
        "assessment": _assess(points, max_drawdown_pct),
    }


def _assess(points: list[dict[str, Any]], max_drawdown_pct: float) -> list[str]:
    final = points[-1]
    projected_points = [point for point in points if point["projected"]]
    realized_points = [point for point in points if not point["projected"]]
    trend = "positive" if final["pnl"] > 0 else "negative" if final["pnl"] < 0 else "flat"
    messages = [
        f"Final simulated P/L is {final['pnl']:.2f} ({final['pnl_pct']:.2f}%), a {trend} outcome for this entry.",
        f"Maximum drawdown from scenario peak is {max_drawdown_pct:.2f}%.",
    ]
    if realized_points and projected_points:
        messages.append("Result blends realized bars through the latest close with model-projected future bars.")
    elif projected_points:
        messages.append("Result is fully forward-looking from the latest close and should be treated as projection only.")
    else:
        messages.append("Result is based only on already available historical bars.")
    return messages
