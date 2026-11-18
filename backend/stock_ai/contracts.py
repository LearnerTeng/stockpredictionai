from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json
from math import isfinite
from typing import Any


DEFAULT_HORIZONS = (5, 20)
DEFAULT_BENCHMARK = "SPY"


@dataclass(frozen=True)
class QuantObjective:
    """Stable contract shared by feature, training, validation and serving code."""

    horizons: tuple[int, ...] = DEFAULT_HORIZONS
    benchmark: str = DEFAULT_BENCHMARK
    price_field: str = "adj_close"
    target: str = "excess_return"

    def __post_init__(self) -> None:
        if not self.horizons or any(horizon < 1 for horizon in self.horizons):
            raise ValueError("horizons must contain positive trading-day values")
        if len(set(self.horizons)) != len(self.horizons):
            raise ValueError("horizons must be unique")
        if not self.benchmark.strip():
            raise ValueError("benchmark is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizons": list(self.horizons),
            "benchmark": self.benchmark,
            "price_field": self.price_field,
            "target": self.target,
            "calendar": "US-equities-trading-days",
        }


def adjusted_price(bar: dict[str, Any]) -> float:
    value = bar.get("adj_close")
    if value is None:
        value = bar.get("close")
    price = float(value)
    if not isfinite(price) or price <= 0:
        raise ValueError("adjusted price must be positive")
    return price


def normalize_bars(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    for bar in bars:
        day = str(bar.get("trade_date") or bar.get("date") or "")
        date.fromisoformat(day)
        if day in seen:
            raise ValueError(f"duplicate daily bar: {day}")
        seen.add(day)
        for field in ("open", "high", "low", "close", "adj_close", "volume"):
            if bar.get(field) is None:
                if field == "close":
                    raise ValueError(f"missing close: {day}")
                continue
            value = float(bar[field])
            if not isfinite(value) or value < 0 or (field != "volume" and value == 0):
                raise ValueError(f"invalid {field}: {day}")
        if bar.get("high") is not None and bar.get("low") is not None:
            if float(bar["high"]) < float(bar["low"]):
                raise ValueError(f"high below low: {day}")
    return sorted(bars, key=lambda bar: str(bar.get("trade_date") or bar.get("date")))


def dataset_version(stock_bars: list[dict[str, Any]], benchmark_by_date: dict[str, float]) -> str:
    """Content hash of every model input, independent of row/dictionary ordering."""
    rows = [
        {"date": str(bar.get("trade_date") or bar.get("date")), **{
            field: float(bar[field]) if bar.get(field) is not None else None
            for field in ("open", "high", "low", "close", "adj_close", "volume")
        }}
        for bar in normalize_bars(stock_bars)
    ]
    payload = json.dumps({"schema": 2, "bars": rows, "benchmark": benchmark_by_date},
                         sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "dataset-" + sha256(payload.encode("utf-8")).hexdigest()


def adjusted_bars(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for original in normalize_bars(bars):
        bar = dict(original)
        raw_close = float(bar["close"])
        adjusted_close = adjusted_price(bar)
        factor = adjusted_close / raw_close if raw_close else 1.0
        for field in ("open", "high", "low"):
            if bar.get(field) is not None:
                bar[field] = float(bar[field]) * factor
        bar["close"] = adjusted_close
        bar["adj_close"] = adjusted_close
        normalized.append(bar)
    return normalized
