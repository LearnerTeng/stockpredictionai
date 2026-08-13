from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from statistics import mean
from typing import Any

from flask import Flask, abort, jsonify, request, send_from_directory
from flask_cors import CORS
from market_data.service import store as market_data_store
from stock_ai.data import DEFAULT_RANGE_OPTIONS, list_value as stock_list_value
from stock_ai.features import (
    ema as stock_ema,
    fourier_trend as stock_fourier_trend,
    rsi as stock_rsi,
    sma as stock_sma,
)
from stock_ai.pipeline import PredictionRequest, StockAiPipeline
from stock_ai.simulation import PositionSimulationConfig
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
YAHOO_RANGE_OPTIONS = DEFAULT_RANGE_OPTIONS
stock_ai_pipeline = StockAiPipeline()


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
    return stock_ai_pipeline.market_data.fetch_prices(symbol)


def _fetch_yahoo_bars(symbol: str, range_value: str = "1y") -> list[dict[str, Any]]:
    return stock_ai_pipeline.market_data.fetch_daily_bars(symbol, range_value)


def _list_value(values: Any, index: int) -> Any:
    return stock_list_value(values, index)


def _sma(values: list[float], window: int) -> float | None:
    return stock_sma(values, window)


def _ema(values: list[float], window: int) -> float | None:
    return stock_ema(values, window)


def _rsi(values: list[float], window: int = 14) -> float | None:
    return stock_rsi(values, window)


def _fourier_trend(values: list[float]) -> dict[str, Any]:
    return stock_fourier_trend(values)


def _build_monitor_signal(symbol: str, bars: list[dict[str, Any]]) -> dict[str, Any]:
    return stock_ai_pipeline.build_signal(symbol, bars)


def _predict_next(window: list[float]) -> float:
    return stock_ai_pipeline.forecaster.predict_next(window)


def _forecast_series(series: list[float], history_window: int, forecast_steps: int) -> list[float]:
    return stock_ai_pipeline.forecaster.forecast_series(series, history_window, forecast_steps)


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
        result = stock_ai_pipeline.predict(
            PredictionRequest(
                symbol=req.symbol,
                history_window=req.history_window,
                forecast_steps=req.forecast_steps,
            )
        )
        return jsonify(result), 200
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


@app.get("/pipeline/architecture")
def pipeline_architecture() -> tuple[Any, int]:
    return jsonify(
        {
            "modules": [
                {
                    "step": 1,
                    "name": "data",
                    "path": "backend/stock_ai/data.py",
                    "current": "Yahoo chart API provider + news provider interface",
                    "extension": "Add yfinance/API/crawler provider behind MarketDataProvider or NewsProvider.",
                },
                {
                    "step": 2,
                    "name": "features",
                    "path": "backend/stock_ai/features.py",
                    "current": "SMA, EMA, RSI, volatility, Fourier trend",
                    "extension": "Add qlib or custom feature sets behind TechnicalFeatureEngineer.",
                },
                {
                    "step": 3,
                    "name": "models",
                    "path": "backend/stock_ai/models.py",
                    "current": "Lightweight statistical forecaster",
                    "extension": "Swap in LSTM/Transformer/FinBERT adapters with the same forecast contract.",
                },
                {
                    "step": 4,
                    "name": "strategy",
                    "path": "backend/stock_ai/strategy.py",
                    "current": "Recommendation score with recommended > 50% flag",
                    "extension": "Tune ScorePolicy thresholds and component weights.",
                },
                {
                    "step": 5,
                    "name": "backtesting",
                    "path": "backend/stock_ai/backtesting.py",
                    "current": "Dependency-light threshold backtester",
                    "extension": "Wire Backtrader behind the same run contract.",
                },
                {
                    "step": 6,
                    "name": "notifications",
                    "path": "backend/stock_ai/notifications.py",
                    "current": "Dry-run app notification dispatcher",
                    "extension": "Add email, LINE, or app notifier implementations.",
                },
                {
                    "step": 7,
                    "name": "execution",
                    "path": "backend/stock_ai/execution.py",
                    "current": "Manual order ticket only",
                    "extension": "Keep brokerage submission outside this app unless explicit compliance work is done.",
                },
            ],
            "entrypoint": "backend/stock_ai/pipeline.py",
            "safety": "The pipeline can generate recommendations and manual order tickets, but it does not send live broker orders.",
        }
    ), 200


def _resolve_signal_payload(payload: dict[str, Any]) -> dict[str, Any]:
    signal = payload.get("signal")
    if isinstance(signal, dict):
        return signal

    symbol = str(payload.get("symbol", "")).strip().upper()
    if not symbol:
        raise ValueError("symbol or signal is required")

    bars = payload.get("bars")
    if isinstance(bars, list) and bars:
        return stock_ai_pipeline.build_signal(symbol, bars)

    local_bars = market_data_store.list_daily_bars(symbol, int(payload.get("limit", 260)))
    if local_bars:
        return stock_ai_pipeline.build_signal(symbol, local_bars)

    range_value = str(payload.get("range", "1y") or "1y")
    yahoo_bars = _fetch_yahoo_bars(symbol, range_value)
    return stock_ai_pipeline.build_signal(symbol, yahoo_bars)


@app.post("/backtest/run")
def backtest_run() -> tuple[Any, int]:
    try:
        payload = _require_json_object()
        symbol = str(payload.get("symbol", "")).strip().upper()
        if not symbol:
            raise ValueError("symbol is required")

        bars = payload.get("bars")
        if not isinstance(bars, list) or not bars:
            local_bars = market_data_store.list_daily_bars(symbol, int(payload.get("limit", 500)))
            bars = local_bars or _fetch_yahoo_bars(symbol, str(payload.get("range", "1y") or "1y"))

        return jsonify(stock_ai_pipeline.backtest(symbol, bars)), 200
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    except Exception as err:  # noqa: BLE001
        return jsonify({"error": f"Backtest failed: {err}"}), 500


@app.post("/simulation/position")
def position_simulation() -> tuple[Any, int]:
    try:
        payload = _require_json_object()
        symbol = str(payload.get("symbol", "")).strip().upper()
        if not symbol:
            raise ValueError("symbol is required")

        quantity = float(payload.get("quantity", 1))
        entry_price = payload.get("entry_price")
        entry_date = payload.get("entry_date")
        forecast_steps = int(payload.get("forecast_steps", 20))
        bars = payload.get("bars")
        if not isinstance(bars, list) or not bars:
            local_bars = market_data_store.list_daily_bars(symbol, int(payload.get("limit", 260)))
            bars = local_bars or _fetch_yahoo_bars(symbol, str(payload.get("range", "1y") or "1y"))
            if bars:
                market_data_store.ingest_daily_bars(symbol, bars, source="simulation-yahoo")

        config = PositionSimulationConfig(
            quantity=quantity,
            entry_price=float(entry_price) if entry_price not in (None, "") else None,
            entry_date=str(entry_date) if entry_date not in (None, "") else None,
            forecast_steps=forecast_steps,
        )
        return jsonify(stock_ai_pipeline.simulate_position(symbol, bars, config)), 200
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    except Exception as err:  # noqa: BLE001
        return jsonify({"error": f"Position simulation failed: {err}"}), 500


@app.post("/notifications/signal")
def notification_signal() -> tuple[Any, int]:
    try:
        payload = _require_json_object()
        signal = _resolve_signal_payload(payload)
        channel = str(payload.get("channel", "app") or "app")
        return jsonify({"notification": stock_ai_pipeline.notify(signal, channel), "signal": signal}), 200
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    except Exception as err:  # noqa: BLE001
        return jsonify({"error": f"Notification failed: {err}"}), 500


@app.post("/manual-orders/ticket")
def manual_order_ticket() -> tuple[Any, int]:
    try:
        payload = _require_json_object()
        signal = _resolve_signal_payload(payload)
        quantity = float(payload.get("quantity", 1))
        ticket = stock_ai_pipeline.manual_order_ticket(signal, quantity)
        return jsonify({"ticket": ticket, "signal": signal}), 201
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    except Exception as err:  # noqa: BLE001
        return jsonify({"error": f"Manual order ticket failed: {err}"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
