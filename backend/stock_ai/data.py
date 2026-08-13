from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_RANGE_OPTIONS = {"3mo", "6mo", "1y", "2y", "5y"}


@dataclass(frozen=True)
class DailyBar:
    symbol: str
    date: str
    open: float | None
    high: float | None
    low: float | None
    close: float
    adj_close: float | None
    volume: int | None
    source: str = "yahoo"

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "date": self.date,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "adj_close": self.adj_close,
            "volume": self.volume,
            "source": self.source,
        }


@dataclass(frozen=True)
class NewsItem:
    symbol: str
    title: str
    url: str | None = None
    published_at: str | None = None
    source: str = "manual"
    sentiment_score: float | None = None


class MarketDataProvider(Protocol):
    def fetch_prices(self, symbol: str, range_value: str = "5y") -> list[float]:
        ...

    def fetch_daily_bars(self, symbol: str, range_value: str = "1y") -> list[dict[str, Any]]:
        ...


class NewsProvider(Protocol):
    def fetch_news(self, symbol: str, limit: int = 20) -> list[NewsItem]:
        ...


class YahooFinanceDataProvider:
    """Yahoo chart API provider.

    This keeps the app dependency-light today. A future yfinance provider can
    implement the same protocol without changing features, models, or routes.
    """

    def __init__(self, timeout_seconds: int = 15):
        self.timeout_seconds = timeout_seconds

    def fetch_prices(self, symbol: str, range_value: str = "5y") -> list[float]:
        payload = self._fetch_chart_payload(symbol, range_value)
        result = (payload.get("chart", {}).get("result") or [{}])[0]
        indicators = result.get("indicators") or {}
        adjclose = indicators.get("adjclose") or []
        quote = indicators.get("quote") or []

        series: list[Any] = []
        if adjclose and isinstance(adjclose[0], dict):
            series = adjclose[0].get("adjclose") or []
        if not series and quote and isinstance(quote[0], dict):
            series = quote[0].get("close") or []

        closes = [float(value) for value in series if value is not None]
        if not closes:
            raise RuntimeError(f"No closing prices returned for symbol {symbol}")
        return closes

    def fetch_daily_bars(self, symbol: str, range_value: str = "1y") -> list[dict[str, Any]]:
        normalized_symbol = normalize_symbol(symbol)
        normalized_range = str(range_value or "1y").strip().lower()
        if normalized_range not in DEFAULT_RANGE_OPTIONS:
            raise ValueError(f"range must be one of: {', '.join(sorted(DEFAULT_RANGE_OPTIONS))}")

        payload = self._fetch_chart_payload(normalized_symbol, normalized_range)
        result = (payload.get("chart", {}).get("result") or [{}])[0]
        timestamps = result.get("timestamp") or []
        indicators = result.get("indicators") or {}
        quote = (indicators.get("quote") or [{}])[0]
        adjclose = (indicators.get("adjclose") or [{}])[0]

        bars: list[dict[str, Any]] = []
        for index, timestamp in enumerate(timestamps):
            close = list_value(quote.get("close"), index)
            if close is None:
                continue
            bar = DailyBar(
                symbol=normalized_symbol,
                date=datetime.fromtimestamp(int(timestamp), timezone.utc).date().isoformat(),
                open=list_value(quote.get("open"), index),
                high=list_value(quote.get("high"), index),
                low=list_value(quote.get("low"), index),
                close=float(close),
                adj_close=list_value(adjclose.get("adjclose"), index),
                volume=list_value(quote.get("volume"), index),
            )
            bars.append(bar.to_dict())

        if not bars:
            raise RuntimeError(f"No daily bars returned for symbol {normalized_symbol}")
        return bars

    def _fetch_chart_payload(self, symbol: str, range_value: str) -> dict[str, Any]:
        normalized_symbol = normalize_symbol(symbol)
        endpoint = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{normalized_symbol}"
            f"?range={range_value}&interval=1d&includeAdjustedClose=true"
        )
        req = Request(
            endpoint,
            headers={
                "User-Agent": "stockpredictionai/1.0",
                "Accept": "application/json",
            },
        )

        try:
            with urlopen(req, timeout=self.timeout_seconds) as response:
                payload = json.load(response)
        except HTTPError as err:
            raise RuntimeError(f"Yahoo Finance returned HTTP {err.code} for {normalized_symbol}") from err
        except URLError as err:
            raise RuntimeError(f"Failed to reach Yahoo Finance: {err.reason}") from err

        chart = payload.get("chart") or {}
        if chart.get("error"):
            message = chart["error"].get("description") or "Unknown upstream error"
            raise RuntimeError(f"Yahoo Finance rejected {normalized_symbol}: {message}")
        return payload


class EmptyNewsProvider:
    """Placeholder for news crawling/API sources.

    The interface is intentionally stable so FinBERT/news sentiment can be added
    without changing scoring or notification code.
    """

    def fetch_news(self, symbol: str, limit: int = 20) -> list[NewsItem]:
        normalize_symbol(symbol)
        if limit < 1:
            raise ValueError("limit must be positive")
        return []


def normalize_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    if not symbol:
        raise ValueError("symbol is required")
    if len(symbol) > 16:
        raise ValueError("symbol must be 16 characters or fewer")
    return symbol


def list_value(values: Any, index: int) -> Any:
    if not isinstance(values, list) or index >= len(values):
        return None
    return values[index]
