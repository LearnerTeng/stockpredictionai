from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from math import cos, pi, sin, sqrt
import os
from pathlib import Path
from statistics import StatisticsError, linear_regression, mean, pstdev
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import Flask, abort, jsonify, request, send_from_directory
from flask_cors import CORS
from market_data.service import store as market_data_store
from trading.service import store as trading_store
import requests

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional during transition
    def load_dotenv(*_args, **_kwargs):
        return False

load_dotenv(Path(__file__).with_name(".env"))

app = Flask(__name__)
CORS(app)

AI_DISCLAIMER = (
    "AI-generated interpretation based only on the current prediction payload and historical tail. "
    "It does not include live news, filings, or broader market context and is not investment advice."
)
DEFAULT_OPENAI_MODEL = "gpt-5-mini"
ALLOWED_ANALYSIS_MODES = {"summary", "full"}
DEFAULT_IMAGE_SERVICE_BASE_URL = "http://127.0.0.1:8001"
IMAGE_SERVICE_BASE_URL = os.getenv("IMAGE_SERVICE_BASE_URL", DEFAULT_IMAGE_SERVICE_BASE_URL).rstrip("/")
IMAGE_STORAGE_ROOT = Path(__file__).with_name("image_service") / "storage"
IMAGE_UPLOADS_DIR = IMAGE_STORAGE_ROOT / "uploads"
IMAGE_GENERATED_DIR = IMAGE_STORAGE_ROOT / "generated"
IMAGE_SERVICE_TIMEOUT = (10, 120)


@dataclass
class PredictRequest:
    symbol: str
    history_window: int
    forecast_steps: int


@dataclass
class AnalyzeRequest:
    analysis_mode: str
    prediction: dict[str, Any]


DEFAULT_MONITOR_SYMBOLS = ["AAPL", "MSFT", "NVDA", "GS", "SPY"]
YAHOO_RANGE_OPTIONS = {"3mo", "6mo", "1y", "2y", "5y"}


def _image_service_url(path: str) -> str:
    return f"{IMAGE_SERVICE_BASE_URL}{path}"


def _proxy_image_service_request(
    method: str,
    path: str,
    *,
    json_payload: dict[str, Any] | None = None,
    form_payload: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> tuple[Any, int]:
    try:
        response = requests.request(
            method=method,
            url=_image_service_url(path),
            json=json_payload,
            data=form_payload,
            files=files,
            params=params,
            timeout=IMAGE_SERVICE_TIMEOUT,
        )
    except requests.RequestException as err:
        return jsonify({"error": f"Image service unavailable: {err}"}), 502

    try:
        payload = response.json()
    except ValueError:
        payload = {"error": f"Invalid JSON response from image service path {path}"}

    return jsonify(payload), response.status_code


def _extract_image_upload() -> tuple[dict[str, Any], dict[str, Any]]:
    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        raise ValueError("file is required")

    file_bytes = uploaded.read()
    if not file_bytes:
        raise ValueError("file is required")

    files = {
        "file": (
            uploaded.filename,
            file_bytes,
            uploaded.mimetype or "application/octet-stream",
        )
    }
    form_payload = {
        key: value
        for key in ("algorithm", "options", "generate_image")
        if (value := request.form.get(key)) is not None
    }
    return files, form_payload


def _resolve_asset_directory(asset_path: str) -> tuple[Path, str]:
    path = Path(asset_path)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        abort(404)

    root_name, *remaining = path.parts
    if root_name == "uploads":
        return IMAGE_UPLOADS_DIR, Path(*remaining).as_posix()
    if root_name == "generated":
        return IMAGE_GENERATED_DIR, Path(*remaining).as_posix()
    abort(404)


def _require_json_object() -> dict[str, Any]:
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object")
    return payload


def _require_symbols_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    symbols = payload.get("symbols")
    if not isinstance(symbols, list) or not symbols:
        raise ValueError("symbols must be a non-empty array")
    normalized: list[dict[str, Any]] = []
    for item in symbols:
        if isinstance(item, str):
            normalized.append({"symbol": item})
            continue
        if not isinstance(item, dict):
            raise ValueError("each symbols item must be a string or object")
        normalized.append(item)
    return normalized


def _parse_request(payload: dict) -> PredictRequest:
    symbol = str(payload.get("symbol", "")).strip().upper()
    history_window = int(payload.get("history_window", 30))
    forecast_steps = int(payload.get("forecast_steps", 5))

    if not symbol:
        raise ValueError("symbol is required")
    if history_window < 10 or history_window > 180:
        raise ValueError("history_window must be between 10 and 180")
    if forecast_steps < 1 or forecast_steps > 30:
        raise ValueError("forecast_steps must be between 1 and 30")

    return PredictRequest(
        symbol=symbol,
        history_window=history_window,
        forecast_steps=forecast_steps,
    )


def _coerce_float_list(name: str, values: Any) -> list[float]:
    if not isinstance(values, list) or not values:
        raise ValueError(f"{name} must be a non-empty array")
    try:
        return [float(value) for value in values]
    except (TypeError, ValueError) as err:
        raise ValueError(f"{name} must contain only numeric values") from err


def _parse_analysis_request(payload: dict[str, Any]) -> AnalyzeRequest:
    analysis_mode = str(payload.get("analysis_mode", "")).strip().lower()
    if analysis_mode not in ALLOWED_ANALYSIS_MODES:
        raise ValueError("analysis_mode must be one of: summary, full")

    prediction = payload.get("prediction")
    if not isinstance(prediction, dict):
        raise ValueError("prediction payload is required")

    symbol = str(prediction.get("symbol", "")).strip().upper()
    if not symbol:
        raise ValueError("prediction.symbol is required")

    try:
        history_window = int(prediction.get("history_window"))
        forecast_steps = int(prediction.get("forecast_steps"))
    except (TypeError, ValueError) as err:
        raise ValueError("prediction.history_window and prediction.forecast_steps must be integers") from err

    metrics = prediction.get("metrics")
    if not isinstance(metrics, dict):
        raise ValueError("prediction.metrics is required")

    try:
        mae = float(metrics.get("mae"))
        rmse = float(metrics.get("rmse"))
    except (TypeError, ValueError) as err:
        raise ValueError("prediction.metrics.mae and prediction.metrics.rmse must be numeric") from err

    normalized_prediction = {
        "symbol": symbol,
        "history_window": history_window,
        "forecast_steps": forecast_steps,
        "predictions": _coerce_float_list("prediction.predictions", prediction.get("predictions")),
        "actuals": _coerce_float_list("prediction.actuals", prediction.get("actuals")),
        "historical_tail": _coerce_float_list("prediction.historical_tail", prediction.get("historical_tail")),
        "metrics": {
            "mae": mae,
            "rmse": rmse,
        },
    }

    return AnalyzeRequest(
        analysis_mode=analysis_mode,
        prediction=normalized_prediction,
    )


def _fetch_prices(symbol: str) -> list[float]:
    endpoint = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        "?range=5y&interval=1d&includeAdjustedClose=true"
    )
    req = Request(
        endpoint,
        headers={
            "User-Agent": "stockpredictionai/1.0",
            "Accept": "application/json",
        },
    )

    try:
        with urlopen(req, timeout=15) as response:
            payload = json.load(response)
    except HTTPError as err:
        raise RuntimeError(f"Yahoo Finance returned HTTP {err.code} for {symbol}") from err
    except URLError as err:
        raise RuntimeError(f"Failed to reach Yahoo Finance: {err.reason}") from err

    chart = payload.get("chart") or {}
    if chart.get("error"):
        message = chart["error"].get("description") or "Unknown upstream error"
        raise RuntimeError(f"Yahoo Finance rejected {symbol}: {message}")

    result = (chart.get("result") or [{}])[0]
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


def _fetch_yahoo_bars(symbol: str, range_value: str = "1y") -> list[dict[str, Any]]:
    normalized_symbol = str(symbol or "").strip().upper()
    if not normalized_symbol:
        raise ValueError("symbol is required")

    normalized_range = str(range_value or "1y").strip().lower()
    if normalized_range not in YAHOO_RANGE_OPTIONS:
        raise ValueError(f"range must be one of: {', '.join(sorted(YAHOO_RANGE_OPTIONS))}")

    endpoint = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{normalized_symbol}"
        f"?range={normalized_range}&interval=1d&includeAdjustedClose=true"
    )
    req = Request(
        endpoint,
        headers={
            "User-Agent": "stockpredictionai/1.0",
            "Accept": "application/json",
        },
    )

    try:
        with urlopen(req, timeout=15) as response:
            payload = json.load(response)
    except HTTPError as err:
        raise RuntimeError(f"Yahoo Finance returned HTTP {err.code} for {normalized_symbol}") from err
    except URLError as err:
        raise RuntimeError(f"Failed to reach Yahoo Finance: {err.reason}") from err

    chart = payload.get("chart") or {}
    if chart.get("error"):
        message = chart["error"].get("description") or "Unknown upstream error"
        raise RuntimeError(f"Yahoo Finance rejected {normalized_symbol}: {message}")

    result = (chart.get("result") or [{}])[0]
    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    quote = (indicators.get("quote") or [{}])[0]
    adjclose = (indicators.get("adjclose") or [{}])[0]

    bars: list[dict[str, Any]] = []
    for index, timestamp in enumerate(timestamps):
        close = _list_value(quote.get("close"), index)
        if close is None:
            continue
        bars.append(
            {
                "date": datetime.fromtimestamp(int(timestamp), timezone.utc).date().isoformat(),
                "open": _list_value(quote.get("open"), index),
                "high": _list_value(quote.get("high"), index),
                "low": _list_value(quote.get("low"), index),
                "close": close,
                "adj_close": _list_value(adjclose.get("adjclose"), index),
                "volume": _list_value(quote.get("volume"), index),
            }
        )

    if not bars:
        raise RuntimeError(f"No daily bars returned for symbol {normalized_symbol}")
    return bars


def _list_value(values: Any, index: int) -> Any:
    if not isinstance(values, list) or index >= len(values):
        return None
    value = values[index]
    if value is None:
        return None
    return value


def _sma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return mean(values[-window:])


def _ema(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    alpha = 2 / (window + 1)
    ema_value = mean(values[:window])
    for value in values[window:]:
        ema_value = (value * alpha) + (ema_value * (1 - alpha))
    return ema_value


def _rsi(values: list[float], window: int = 14) -> float | None:
    if len(values) <= window:
        return None
    deltas = [curr - prev for prev, curr in zip(values, values[1:])]
    recent = deltas[-window:]
    gains = [max(delta, 0.0) for delta in recent]
    losses = [abs(min(delta, 0.0)) for delta in recent]
    avg_loss = mean(losses)
    if avg_loss == 0:
        return 100.0
    rs = mean(gains) / avg_loss
    return 100 - (100 / (1 + rs))


def _fourier_trend(values: list[float]) -> dict[str, Any]:
    sample = values[-min(len(values), 90) :]
    if len(sample) < 20:
        return {"direction": "flat", "strength": 0.0}

    detrended = [value - mean(sample) for value in sample]
    n = len(detrended)
    low_frequency_scores: list[float] = []
    for frequency in (1, 2, 3):
        real = sum(value * cos(2 * pi * frequency * index / n) for index, value in enumerate(detrended))
        imag = sum(value * sin(2 * pi * frequency * index / n) for index, value in enumerate(detrended))
        low_frequency_scores.append(sqrt(real**2 + imag**2) / n)

    try:
        slope, _intercept = linear_regression(range(len(sample)), sample)
    except StatisticsError:
        slope = 0.0

    baseline = max(abs(mean(sample)), 1.0)
    strength = min(abs(slope) / baseline * 1000 + sum(low_frequency_scores) / baseline, 1.0)
    direction = "up" if slope > 0 else "down" if slope < 0 else "flat"
    return {
        "direction": direction,
        "strength": round(strength, 4),
        "slope": round(slope, 6),
    }


def _build_monitor_signal(symbol: str, bars: list[dict[str, Any]]) -> dict[str, Any]:
    sorted_bars = sorted(bars, key=lambda bar: bar.get("trade_date") or bar.get("date") or "")
    closes = [float(bar["close"]) for bar in sorted_bars if bar.get("close") is not None]
    if len(closes) < 30:
        raise ValueError(f"{symbol} needs at least 30 bars for monitoring")

    last_bar = sorted_bars[-1]
    latest_close = closes[-1]
    previous_close = closes[-2]
    change = latest_close - previous_close
    change_pct = (change / previous_close * 100) if previous_close else 0.0
    sma_7 = _sma(closes, 7)
    sma_21 = _sma(closes, 21)
    ema_12 = _ema(closes, 12)
    ema_26 = _ema(closes, 26)
    rsi_14 = _rsi(closes, 14)
    recent_returns = [
        (curr - prev) / prev
        for prev, curr in zip(closes[-31:-1], closes[-30:])
        if prev
    ]
    volatility = pstdev(recent_returns) * sqrt(252) if len(recent_returns) > 2 else 0.0
    forecast_steps = 5
    forecast_window = min(45, len(closes) - forecast_steps)
    predictions = _forecast_series(closes[:-forecast_steps], forecast_window, forecast_steps)
    actuals = closes[-forecast_steps:]
    forecast_delta_pct = ((predictions[-1] - latest_close) / latest_close * 100) if latest_close else 0.0
    mae = mean(abs(pred - actual) for pred, actual in zip(predictions, actuals))
    trend = _fourier_trend(closes)

    score = 50.0
    if sma_7 is not None and sma_21 is not None:
        score += 12 if sma_7 > sma_21 else -12
    if ema_12 is not None and ema_26 is not None:
        score += 10 if ema_12 > ema_26 else -10
    if rsi_14 is not None:
        if rsi_14 < 35:
            score += 8
        elif rsi_14 > 70:
            score -= 8
    score += max(min(forecast_delta_pct, 12), -12)
    score += 6 if trend["direction"] == "up" else -6 if trend["direction"] == "down" else 0
    score -= min(volatility * 10, 12)
    score = min(max(score, 0), 100)

    if score >= 68:
        stance = "watch-positive"
    elif score <= 38:
        stance = "watch-risk"
    else:
        stance = "neutral"

    alerts: list[str] = []
    if abs(change_pct) >= 3:
        alerts.append(f"Daily move {change_pct:.2f}% exceeds the 3% monitor threshold.")
    if rsi_14 is not None and rsi_14 >= 70:
        alerts.append("RSI is in an overbought zone.")
    if rsi_14 is not None and rsi_14 <= 30:
        alerts.append("RSI is in an oversold zone.")
    if volatility >= 0.45:
        alerts.append("Annualized recent volatility is elevated.")
    if not alerts:
        alerts.append("No threshold alert on the latest run.")

    return {
        "symbol": symbol,
        "trade_date": last_bar.get("trade_date") or last_bar.get("date"),
        "latest_close": round(latest_close, 4),
        "change": round(change, 4),
        "change_pct": round(change_pct, 4),
        "score": round(score, 2),
        "stance": stance,
        "indicators": {
            "sma_7": round(sma_7, 4) if sma_7 is not None else None,
            "sma_21": round(sma_21, 4) if sma_21 is not None else None,
            "ema_12": round(ema_12, 4) if ema_12 is not None else None,
            "ema_26": round(ema_26, 4) if ema_26 is not None else None,
            "rsi_14": round(rsi_14, 4) if rsi_14 is not None else None,
            "volatility_30d_annualized": round(volatility, 4),
            "fourier_trend": trend,
        },
        "forecast": {
            "steps": forecast_steps,
            "predictions": [round(value, 4) for value in predictions],
            "actuals": [round(value, 4) for value in actuals],
            "delta_pct": round(forecast_delta_pct, 4),
            "mae": round(mae, 4),
        },
        "alerts": alerts,
        "historical_tail": [round(value, 4) for value in closes[-60:]],
    }


def _predict_next(window: list[float]) -> float:
    if len(window) < 3:
        return float(window[-1])

    last_value = window[-1]
    avg_value = mean(window)
    deltas = [curr - prev for prev, curr in zip(window, window[1:])]
    recent_deltas = deltas[-min(8, len(deltas)) :]
    momentum = mean(recent_deltas)

    try:
        slope, intercept = linear_regression(range(len(window)), window)
        trend_estimate = slope * len(window) + intercept
    except StatisticsError:
        trend_estimate = last_value

    volatility = pstdev(recent_deltas) if len(recent_deltas) > 1 else 0.0
    mean_reversion = 0.18 * (last_value - avg_value)
    blended = (0.55 * trend_estimate) + (0.45 * (last_value + momentum)) - mean_reversion
    next_value = last_value + ((blended - last_value) * 0.82)

    if volatility:
        upper = last_value + momentum + (2.2 * volatility)
        lower = last_value + momentum - (2.2 * volatility)
        next_value = min(max(next_value, lower), upper)

    return max(next_value, 0.01)


def _forecast_series(series: list[float], history_window: int, forecast_steps: int) -> list[float]:
    working = list(series[-history_window:])
    preds: list[float] = []
    for _ in range(forecast_steps):
        next_value = _predict_next(working)
        preds.append(next_value)
        working = working[1:] + [next_value]
    return preds


@app.get("/health")
def health() -> tuple[dict, int]:
    return {"ok": True}, 200


@app.get("/data/health")
def data_health() -> tuple[dict[str, Any], int]:
    return {
        "ok": True,
        "summary": market_data_store.universe_summary(),
    }, 200


@app.get("/data/symbols")
def data_symbols() -> tuple[dict[str, Any], int]:
    return {"items": market_data_store.list_symbols()}, 200


@app.post("/data/symbols")
def data_upsert_symbols() -> tuple[Any, int]:
    try:
        payload = _require_json_object()
        items = _require_symbols_payload(payload)
        result = market_data_store.upsert_symbols(items)
        return jsonify({"items": result}), 200
    except ValueError as err:
        return jsonify({"error": str(err)}), 400


@app.get("/data/import-batches")
def data_import_batches() -> tuple[dict[str, Any], int]:
    return {"items": market_data_store.list_import_batches()}, 200


@app.get("/data/import-batches/<batch_id>")
def data_import_batch_detail(batch_id: str) -> tuple[Any, int]:
    try:
        return jsonify(market_data_store.get_import_batch(batch_id)), 200
    except ValueError as err:
        status = 404 if "not found" in str(err) else 400
        return jsonify({"error": str(err)}), status


@app.post("/data/import-batches")
def data_create_import_batch() -> tuple[Any, int]:
    try:
        payload = _require_json_object()
        items = _require_symbols_payload(payload)
        symbols = [item["symbol"] if isinstance(item, dict) else str(item) for item in items]
        result = market_data_store.create_import_batch(
            symbols=symbols,
            source=str(payload.get("source", "manual-plan") or "manual-plan"),
            notes=str(payload.get("notes", "") or "").strip() or None,
        )
        return jsonify(result), 201
    except ValueError as err:
        return jsonify({"error": str(err)}), 400


@app.post("/data/prices/bulk")
def data_ingest_prices_bulk() -> tuple[Any, int]:
    try:
        payload = _require_json_object()
        symbol = payload.get("symbol")
        bars = payload.get("bars")
        if not isinstance(bars, list) or not bars:
            raise ValueError("bars must be a non-empty array")
        result = market_data_store.ingest_daily_bars(
            symbol=str(symbol or ""),
            bars=bars,
            source=str(payload.get("source", "manual-bulk") or "manual-bulk"),
            batch_id=str(payload.get("batch_id", "") or "").strip() or None,
        )
        return jsonify(result), 200
    except ValueError as err:
        return jsonify({"error": str(err)}), 400


@app.get("/data/prices/<symbol>")
def data_list_prices(symbol: str) -> tuple[Any, int]:
    try:
        limit = int(request.args.get("limit", 60))
        return jsonify({"items": market_data_store.list_daily_bars(symbol, limit)}), 200
    except ValueError as err:
        return jsonify({"error": str(err)}), 400


@app.post("/data/import-yahoo")
def data_import_yahoo() -> tuple[Any, int]:
    try:
        payload = _require_json_object()
        items = _require_symbols_payload(payload)
        symbols = [str(item.get("symbol", item) if isinstance(item, dict) else item) for item in items]
        range_value = str(payload.get("range", "1y") or "1y")
        batch = market_data_store.create_import_batch(
            symbols=symbols,
            source=f"yahoo-{range_value}",
            notes="Imported by local monitor",
        )

        imported: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for symbol in symbols:
            normalized_symbol = str(symbol).strip().upper()
            try:
                bars = _fetch_yahoo_bars(normalized_symbol, range_value)
                result = market_data_store.ingest_daily_bars(
                    normalized_symbol,
                    bars,
                    source="yahoo",
                    batch_id=batch["id"],
                )
                imported.append(result)
            except Exception as err:  # noqa: BLE001
                errors.append({"symbol": normalized_symbol, "error": str(err)})

        return jsonify({"batch": market_data_store.get_import_batch(batch["id"]), "imported": imported, "errors": errors}), 200
    except ValueError as err:
        return jsonify({"error": str(err)}), 400


@app.post("/monitor/run")
def monitor_run() -> tuple[Any, int]:
    try:
        payload = _require_json_object()
        raw_symbols = payload.get("symbols", DEFAULT_MONITOR_SYMBOLS)
        if isinstance(raw_symbols, str):
            symbols = [symbol.strip().upper() for symbol in raw_symbols.split(",") if symbol.strip()]
        elif isinstance(raw_symbols, list):
            symbols = [str(symbol).strip().upper() for symbol in raw_symbols if str(symbol).strip()]
        else:
            raise ValueError("symbols must be an array or comma-separated string")
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")

        range_value = str(payload.get("range", "1y") or "1y")
        results: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for symbol in symbols:
            try:
                bars = _fetch_yahoo_bars(symbol, range_value)
                market_data_store.ingest_daily_bars(symbol, bars, source="yahoo-monitor")
                results.append(_build_monitor_signal(symbol, bars))
            except Exception as err:  # noqa: BLE001
                errors.append({"symbol": symbol, "error": str(err)})

        trading_store.upsert_monitor_signals(results)

        return jsonify(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "range": range_value,
                "items": results,
                "errors": errors,
                "disclaimer": "Local monitoring signal only. It is not investment advice.",
            }
        ), 200
    except ValueError as err:
        return jsonify({"error": str(err)}), 400


@app.get("/monitor/status")
def monitor_status() -> tuple[Any, int]:
    raw_symbols = request.args.get("symbols", "")
    symbols = [symbol.strip().upper() for symbol in raw_symbols.split(",") if symbol.strip()]
    if not symbols:
        symbols = [item["symbol"] for item in market_data_store.list_symbols()[:8]] or DEFAULT_MONITOR_SYMBOLS

    items: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for symbol in symbols:
        try:
            bars = market_data_store.list_daily_bars(symbol, 260)
            if not bars:
                errors.append({"symbol": symbol, "error": "No local bars. Run monitor refresh first."})
                continue
            items.append(_build_monitor_signal(symbol, bars))
        except Exception as err:  # noqa: BLE001
            errors.append({"symbol": symbol, "error": str(err)})

    return jsonify(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "items": items,
            "errors": errors,
            "summary": market_data_store.universe_summary(),
        }
    ), 200


@app.get("/dashboard")
def dashboard() -> tuple[Any, int]:
    return jsonify(trading_store.get_dashboard()), 200


@app.get("/recommendations")
def recommendations() -> tuple[Any, int]:
    return jsonify({"items": trading_store.list_recommendations(), "data_mode": "demo"}), 200


@app.get("/recommendations/<symbol>")
def recommendation_detail(symbol: str) -> tuple[Any, int]:
    try:
        return jsonify(trading_store.get_recommendation(symbol)), 200
    except ValueError as err:
        status = 404 if "not found" in str(err) else 400
        return jsonify({"error": str(err)}), status


@app.get("/portfolio")
def portfolio() -> tuple[Any, int]:
    try:
        return jsonify(trading_store.get_portfolio()), 200
    except ValueError as err:
        return jsonify({"error": str(err)}), 404


@app.get("/portfolio/performance")
def portfolio_performance() -> tuple[Any, int]:
    try:
        return jsonify(trading_store.get_performance()), 200
    except ValueError as err:
        return jsonify({"error": str(err)}), 404


@app.get("/trading/orders")
def trading_orders() -> tuple[Any, int]:
    try:
        limit = int(request.args.get("limit", 50))
        return jsonify({"items": trading_store.list_orders(limit), "mode": "paper"}), 200
    except ValueError as err:
        return jsonify({"error": str(err)}), 400


@app.post("/trading/orders")
def trading_create_order() -> tuple[Any, int]:
    try:
        payload = _require_json_object()
        client_order_id = request.headers.get("Idempotency-Key")
        order = trading_store.create_order(payload, client_order_id)
        return jsonify(order), 201
    except ValueError as err:
        return jsonify({"error": str(err)}), 400


@app.post("/trading/orders/<order_id>/confirm")
def trading_confirm_order(order_id: str) -> tuple[Any, int]:
    try:
        return jsonify(trading_store.confirm_order(order_id)), 200
    except ValueError as err:
        status = 404 if "not found" in str(err) else 409
        return jsonify({"error": str(err)}), status


@app.get("/image/health")
def image_health() -> tuple[Any, int]:
    return _proxy_image_service_request("GET", "/health")


@app.post("/image/analyze")
def image_analyze() -> tuple[Any, int]:
    try:
        files, form_payload = _extract_image_upload()
    except ValueError as err:
        return jsonify({"error": str(err)}), 400

    return _proxy_image_service_request(
        "POST",
        "/image/analyze",
        form_payload=form_payload,
        files=files,
    )


@app.post("/image/jobs")
def image_jobs() -> tuple[Any, int]:
    try:
        files, form_payload = _extract_image_upload()
    except ValueError as err:
        return jsonify({"error": str(err)}), 400

    return _proxy_image_service_request(
        "POST",
        "/image/jobs",
        form_payload=form_payload,
        files=files,
    )


@app.get("/image/jobs/<job_id>")
def image_job_detail(job_id: str) -> tuple[Any, int]:
    return _proxy_image_service_request("GET", f"/image/jobs/{job_id}")


@app.get("/image/history")
def image_history() -> tuple[Any, int]:
    params = {
        key: value
        for key in ("page", "page_size")
        if (value := request.args.get(key)) is not None
    }
    return _proxy_image_service_request("GET", "/image/history", params=params)


@app.post("/image/render")
def image_render() -> tuple[Any, int]:
    return _proxy_image_service_request(
        "POST",
        "/image/render",
        json_payload=request.get_json(silent=True) or {},
    )


@app.get("/image/assets/<path:asset_path>")
def image_assets(asset_path: str):
    directory, filename = _resolve_asset_directory(asset_path)
    if not filename:
        abort(404)
    return send_from_directory(directory, filename)


def _build_analysis_prompt(req: AnalyzeRequest) -> tuple[str, str]:
    prediction = req.prediction
    history_sample = prediction["historical_tail"][-12:]
    forecast_sample = prediction["predictions"]
    actual_sample = prediction["actuals"]

    mode_instruction = (
        "Produce a concise executive summary with 2-3 short sections and brief bullets."
        if req.analysis_mode == "summary"
        else "Produce a fuller analysis with 3-5 sections and practical but non-prescriptive bullets."
    )

    system_prompt = (
        "You are a market analysis assistant for a stock prediction dashboard. "
        "Use only the supplied prediction payload. "
        "Do not claim access to live prices, market news, earnings, macro events, or external data. "
        "Do not give direct buy or sell recommendations. "
        "Focus on interpreting the model output, forecast shape, errors, uncertainty cues, and operational cautions. "
        f"{mode_instruction}"
    )

    user_prompt = (
        "Interpret the following prediction payload and return structured analysis.\n\n"
        f"analysis_mode: {req.analysis_mode}\n"
        f"symbol: {prediction['symbol']}\n"
        f"history_window: {prediction['history_window']}\n"
        f"forecast_steps: {prediction['forecast_steps']}\n"
        f"metrics: {json.dumps(prediction['metrics'])}\n"
        f"historical_tail_sample: {json.dumps(history_sample)}\n"
        f"predictions: {json.dumps(forecast_sample)}\n"
        f"actuals: {json.dumps(actual_sample)}\n"
    )

    return system_prompt, user_prompt


def _analysis_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "heading": {"type": "string"},
                        "bullets": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["heading", "bullets"],
                },
            },
        },
        "required": ["title", "summary", "sections"],
    }


def _create_openai_client():
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    try:
        from openai import OpenAI
    except ImportError:
        return None

    return OpenAI(api_key=api_key)


def _build_local_analysis(req: AnalyzeRequest) -> dict[str, Any]:
    prediction = req.prediction
    historical = prediction["historical_tail"]
    forecasts = prediction["predictions"]
    actuals = prediction["actuals"]
    metrics = prediction["metrics"]

    last_close = historical[-1]
    avg_forecast = mean(forecasts)
    delta = avg_forecast - last_close
    delta_pct = (delta / last_close * 100) if last_close else 0.0
    direction = "upward" if delta > 0 else "downward" if delta < 0 else "flat"
    spread = max(forecasts) - min(forecasts) if len(forecasts) > 1 else 0.0
    realized_bias = mean(pred - actual for pred, actual in zip(forecasts, actuals))

    sections = [
        {
            "heading": "Forecast Shape",
            "bullets": [
                f"The near-term path is {direction}, with an average projected move of {delta_pct:.2f}% versus the latest close.",
                f"Projected values span {min(forecasts):.2f} to {max(forecasts):.2f}, creating a forecast spread of {spread:.2f}.",
            ],
        },
        {
            "heading": "Error Readout",
            "bullets": [
                f"Held-out backtest error is MAE {metrics['mae']:.4f} and RMSE {metrics['rmse']:.4f}.",
                f"Average forecast bias versus actuals is {realized_bias:.4f}; positive means the model overshot on average.",
            ],
        },
    ]

    if req.analysis_mode == "full":
        sections.append(
            {
                "heading": "Operational Cautions",
                "bullets": [
                    "This environment is using a lightweight statistical forecast so the demo can run without heavy native dependencies.",
                    "Treat the output as directional support, not an investment instruction or a substitute for broader market context.",
                ],
            }
        )

    return {
        "analysis_mode": req.analysis_mode,
        "title": f"{prediction['symbol']} forecast shows a {direction} near-term bias",
        "summary": (
            f"The forecast average is {avg_forecast:.2f} versus the latest close of {last_close:.2f}, "
            f"with MAE {metrics['mae']:.4f} and RMSE {metrics['rmse']:.4f} over the evaluation window."
        ),
        "sections": sections,
        "disclaimer": AI_DISCLAIMER,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _generate_ai_analysis(req: AnalyzeRequest) -> dict[str, Any]:
    client = _create_openai_client()
    if client is None:
        return _build_local_analysis(req)

    system_prompt, user_prompt = _build_analysis_prompt(req)
    model = os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip() or DEFAULT_OPENAI_MODEL

    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "system",
                "content": [{"type": "input_text", "text": system_prompt}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": user_prompt}],
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "prediction_analysis",
                "schema": _analysis_schema(),
                "strict": True,
            }
        },
        max_output_tokens=700 if req.analysis_mode == "summary" else 1200,
    )

    output_text = getattr(response, "output_text", None)
    if not output_text:
        return _build_local_analysis(req)

    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError:
        return _build_local_analysis(req)

    return {
        "analysis_mode": req.analysis_mode,
        "title": parsed["title"],
        "summary": parsed["summary"],
        "sections": parsed["sections"],
        "disclaimer": AI_DISCLAIMER,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/predict")
def predict() -> tuple[dict, int]:
    try:
        req = _parse_request(request.get_json(silent=True) or {})
        closes = _fetch_prices(req.symbol)
        min_needed = req.history_window + req.forecast_steps + 20
        if len(closes) < min_needed:
            return (
                jsonify(
                    {
                        "error": (
                            f"Not enough data for {req.symbol}. "
                            f"Need at least {min_needed} daily prices, found {len(closes)}"
                        )
                    }
                ),
                400,
            )

        train_end = len(closes) - req.forecast_steps
        train_series = closes[:train_end]
        test_series = closes[train_end:]
        preds = _forecast_series(train_series, req.history_window, req.forecast_steps)

        mae = mean(abs(pred - actual) for pred, actual in zip(preds, test_series))
        rmse = sqrt(mean((pred - actual) ** 2 for pred, actual in zip(preds, test_series)))

        historical_tail_len = min(60, len(closes))
        historical_tail = closes[-historical_tail_len:]

        return (
            jsonify(
                {
                    "symbol": req.symbol,
                    "history_window": req.history_window,
                    "forecast_steps": req.forecast_steps,
                    "predictions": [round(v, 4) for v in preds],
                    "actuals": [round(v, 4) for v in test_series],
                    "metrics": {
                        "mae": round(mae, 4),
                        "rmse": round(rmse, 4),
                    },
                    "historical_tail": [round(v, 4) for v in historical_tail],
                }
            ),
            200,
        )
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    except Exception as err:  # noqa: BLE001
        return jsonify({"error": f"Prediction failed: {err}"}), 500


@app.post("/ai/analyze")
def analyze() -> tuple[dict, int]:
    try:
        req = _parse_analysis_request(request.get_json(silent=True) or {})
        result = _generate_ai_analysis(req)
        return jsonify(result), 200
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    except RuntimeError as err:
        message = str(err)
        status = 503 if "OPENAI_API_KEY" in message or "SDK" in message else 502
        return jsonify({"error": message}), status
    except Exception as err:  # noqa: BLE001
        return jsonify({"error": f"AI analysis failed: {err}"}), 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
