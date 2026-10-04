"""Offline experiments and an operator-owned, local model registry.

Pickles are read only from the configured trusted registry, never from API uploads.
The content digest detects corruption; it is not a signature or a trust boundary.
"""
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import pickle
import platform
import re
from statistics import mean
from uuid import uuid4

from .backtesting import BacktestConfig, ThresholdBacktester
from .contracts import adjusted_bars, adjusted_price, dataset_version, normalize_bars
from .excess_returns import MultiHorizonExcessReturnForecaster
from .ml_features import FEATURE_NAMES


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(temporary, path)


def evaluate_excess(stock, benchmark, folds=12):
    """Expanding folds: each label is realized AFTER the corresponding fit cutoff.

    Origins are 20 bars apart so the longest (20-day) evaluation labels do not overlap.
    No hyperparameters are selected using these folds.
    """
    benchmark_map = {str(b.get("trade_date") or b.get("date")): adjusted_price(b) for b in normalize_bars(benchmark)}
    stock = [b for b in adjusted_bars(stock) if str(b.get("trade_date") or b.get("date")) in benchmark_map]
    first = 221
    cuts = list(range(first, len(stock) - 20, 20))[-folds:]
    if len(cuts) < 3:
        raise ValueError("at least 282 aligned bars are required for three evaluation folds")
    observations = {5: [], 20: []}
    for cut in cuts:
        history = stock[:cut + 1]
        cutoff = str(history[-1].get("trade_date") or history[-1].get("date"))
        past_benchmark = [b for b in benchmark if str(b.get("trade_date") or b.get("date")) <= cutoff]
        candidate = MultiHorizonExcessReturnForecaster(allow_training=True)
        prediction = candidate.predict(history, past_benchmark)
        if prediction["fallback_used"]:
            raise ValueError("offline fitting unavailable: " + prediction["fallback_reason"])
        baseline = MultiHorizonExcessReturnForecaster().predict(history, past_benchmark)
        for predicted, reference in zip(prediction["forecasts"], baseline["forecasts"]):
            horizon = predicted["horizon_days"]
            end = stock[cut + horizon]
            end_date = str(end.get("trade_date") or end.get("date"))
            actual = (adjusted_price(end) / adjusted_price(stock[cut]) - benchmark_map[end_date] / benchmark_map[cutoff]) * 100
            observations[horizon].append({"as_of": cutoff, "label_end": end_date,
                "actual_pct": actual, "predicted_pct": predicted["excess_return_pct"],
                "baseline_pct": reference["excess_return_pct"]})
    metrics = []
    for horizon, rows in observations.items():
        metrics.append({"horizon_days": horizon, "folds": len(rows),
            "mae_pct": mean(abs(r["predicted_pct"] - r["actual_pct"]) for r in rows),
            "baseline_mae_pct": mean(abs(r["baseline_pct"] - r["actual_pct"]) for r in rows),
            "zero_mae_pct": mean(abs(r["actual_pct"]) for r in rows),
            "direction_accuracy": mean((r["predicted_pct"] > 0) == (r["actual_pct"] > 0) for r in rows),
            "observations": rows})
    return {"method": "expanding-nonoverlapping-labels", "metrics": metrics,
            "eligible": all(r["folds"] >= 12 and r["mae_pct"] < min(r["baseline_mae_pct"], r["zero_mae_pct"]) for r in metrics),
            "gate": "Each horizon: >=12 folds and MAE better than relative momentum and zero excess. Research serving only; no live-trading approval."}


def train_run(root: Path, symbol: str, stock, benchmark):
    import sklearn

    if not re.fullmatch(r"[A-Z][A-Z0-9-]{0,15}", symbol):
        raise ValueError("this objective supports US equity symbols against SPY only")
    stock, benchmark = normalize_bars(stock), normalize_bars(benchmark)
    benchmark_map = {str(b.get("trade_date") or b.get("date")): adjusted_price(b) for b in benchmark}
    validation = evaluate_excess(stock, benchmark)
    model = MultiHorizonExcessReturnForecaster(allow_training=True)
    trained = model.predict(stock, benchmark)
    if trained["fallback_used"]:
        raise ValueError(trained["fallback_reason"])
    model.allow_training = False
    run_id = uuid4().hex
    directory = root / run_id
    directory.mkdir(parents=True, exist_ok=False)
    snapshot = {"symbol": symbol, "stock": stock, "benchmark": benchmark}
    write_json(directory / "dataset.json", snapshot)
    artifact = pickle.dumps(model, protocol=pickle.HIGHEST_PROTOCOL)
    (directory / "model.pkl").write_bytes(artifact)
    source_hashes = {}
    (directory / "code").mkdir()
    for name in ("contracts.py", "features.py", "ml_features.py", "models.py", "excess_returns.py", "strategy.py", "backtesting.py", "research.py"):
        source = Path(__file__).with_name(name).read_bytes()
        (directory / "code" / name).write_bytes(source)
        source_hashes[name] = sha256(source).hexdigest()
    # These assess the EXISTING threshold strategy, not the excess-return model.
    costs = []
    for multiplier in (0, 1, 2):
        result = ThresholdBacktester().run(symbol, stock, BacktestConfig(commission_pct=.001 * multiplier, slippage_pct=.0005 * multiplier))
        costs.append({"cost_multiplier": multiplier, "return_pct": result["return_pct"],
                      "excess_vs_buy_hold_pct": result["excess_vs_buy_hold_pct"], "metrics": result["metrics"]})
    manifest = {"schema": 1, "run_id": run_id, "symbol": symbol, "created_at": datetime.now(timezone.utc).isoformat(),
        "trained_until": model.trained_until, "dataset_version": dataset_version(stock, benchmark_map),
        "features": list(FEATURE_NAMES), "objective": model.objective.to_dict(),
        "python": platform.python_version(), "sklearn": sklearn.__version__,
        "source_sha256": source_hashes,
        "model_parameters": {str(h): fitted.get_params() for h, fitted in model.fitted_models.items()},
        "artifact_sha256": sha256(artifact).hexdigest(),
        "snapshot_sha256": sha256((directory / "dataset.json").read_bytes()).hexdigest(),
        "validation": validation, "threshold_strategy_cost_sensitivity": costs,
        "limitations": ["Single-symbol validation; no historical-universe correction.",
                        "Repeated experiments require a separate untouched holdout.",
                        "Predictive-error gate does not establish profitable portfolio returns."]}
    write_json(directory / "manifest.json", manifest)
    return manifest


def read_run(root, run_id):
    if not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise ValueError("invalid run id")
    directory = root / run_id
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest["run_id"] != run_id or manifest["schema"] != 1 or manifest["features"] != list(FEATURE_NAMES):
        raise ValueError("incompatible model manifest")
    return directory, manifest


def activate_run(root, run_id):
    directory, manifest = read_run(root, run_id)
    if not manifest["validation"]["eligible"]:
        raise ValueError("model failed the sample-out-of-training gate")
    if sha256((directory / "model.pkl").read_bytes()).hexdigest() != manifest["artifact_sha256"]:
        raise ValueError("model artifact checksum mismatch")
    active_path = root / "active.json"
    active = json.loads(active_path.read_text(encoding="utf-8")) if active_path.exists() else {}
    previous = active.get(manifest["symbol"])
    active[manifest["symbol"]] = run_id
    write_json(root / "activations" / (uuid4().hex + ".json"), {
        "at": datetime.now(timezone.utc).isoformat(), "symbol": manifest["symbol"], "previous": previous, "run_id": run_id})
    write_json(active_path, active)
    return {"symbol": manifest["symbol"], "run_id": run_id, "previous": previous}


def score_archived_predictions(root, symbol, stock, benchmark):
    """Evaluate only predictions recorded before their first future bar date.

    Duplicate requests at one cutoff count once per model/horizon. Historical
    requests recorded after the outcome started are explicitly excluded.
    """
    stock = adjusted_bars(stock)
    lookup = {str(b.get("trade_date") or b.get("date")): i for i, b in enumerate(stock)}
    benchmark_map = {str(b.get("trade_date") or b.get("date")): adjusted_price(b) for b in normalize_bars(benchmark)}
    rows, seen = [], set()
    pending = retrospective = 0
    archives = [json.loads(path.read_text(encoding="utf-8")) for path in (root / "predictions").glob("*.json")]
    for archive in sorted(archives, key=lambda item: item["recorded_at"]):
        if archive["symbol"] != symbol:
            continue
        prediction = archive["prediction"]
        cutoff = prediction.get("data_cutoff")
        index = lookup.get(cutoff)
        if index is None or index + 1 >= len(stock):
            pending += 1
            continue
        next_date = str(stock[index + 1].get("trade_date") or stock[index + 1].get("date"))
        if archive["recorded_at"][:10] >= next_date:
            retrospective += 1
            continue
        for forecast in prediction["forecasts"]:
            horizon = forecast["horizon_days"]
            model = prediction.get("model_run_id") or prediction["model_id"]
            key = model, cutoff, horizon
            if key in seen:
                continue
            seen.add(key)
            if index + horizon >= len(stock):
                pending += 1
                continue
            end = stock[index + horizon]
            end_date = str(end.get("trade_date") or end.get("date"))
            if cutoff not in benchmark_map or end_date not in benchmark_map:
                pending += 1
                continue
            actual = (adjusted_price(end) / adjusted_price(stock[index]) - benchmark_map[end_date] / benchmark_map[cutoff]) * 100
            rows.append({"model": model, "as_of": cutoff, "horizon_days": horizon, "label_end": end_date,
                         "predicted_pct": forecast["excess_return_pct"], "actual_pct": actual,
                         "absolute_error_pct": abs(forecast["excess_return_pct"] - actual)})
    result = {"symbol": symbol, "evaluated": len(rows), "pending": pending, "retrospective_excluded": retrospective,
              "observations": rows, "note": "Overlapping horizons are not independent samples; no significance or profitability claim."}
    write_json(root / "evaluations" / (uuid4().hex + ".json"), result)
    return result


def registered_prediction(root: Path, symbol, stock, benchmark):
    import sklearn

    active = json.loads((root / "active.json").read_text(encoding="utf-8"))
    run_id = active.get(symbol)
    if run_id is None:
        raise ValueError("no active model for symbol")
    directory, manifest = read_run(root, run_id)
    if manifest["symbol"] != symbol or not manifest["validation"]["eligible"]:
        raise ValueError("model symbol or validation gate mismatch")
    if manifest["python"] != platform.python_version() or manifest["sklearn"] != sklearn.__version__:
        raise ValueError("model runtime version mismatch; retrain before serving")
    if (date.today() - date.fromisoformat(manifest["trained_until"])).days > 90:
        raise ValueError("registered model is older than 90 days")
    content = (directory / "model.pkl").read_bytes()
    if sha256(content).hexdigest() != manifest["artifact_sha256"]:
        raise ValueError("model artifact checksum mismatch")
    model = pickle.loads(content)  # Trusted operator-owned registry only; no user-supplied paths.
    model.allow_training = False
    prediction = model.predict(stock, benchmark)
    prediction["model_run_id"] = run_id
    prediction["validation"] = manifest["validation"]
    prediction["production_eligible"] = False
    return prediction
