"""Forward outcome monitoring. Never tunes or retrains a model."""
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import mean
from uuid import uuid4

from market_data.calendar import latest_completed_session
from .research import score_archived_predictions, write_json, registered_prediction


def summarize(rows, min_samples=20):
    if not isinstance(min_samples, int) or min_samples < 3:
        raise ValueError("min_samples must be an integer >=3")
    grouped = {}
    for row in rows:
        grouped.setdefault((row["model"], row["horizon_days"]), []).append(row)
    reports = []
    for (model, horizon), observations in grouped.items():
        # Keep non-overlapping outcomes; dense daily requests are not independent trials.
        independent, last_end = [], ""
        for row in sorted(observations, key=lambda r: r["as_of"]):
            if row["as_of"] < last_end:
                continue
            independent.append(row)
            last_end = row["label_end"]
        recent = independent[-60:]
        mae = mean(r["absolute_error_pct"] for r in recent)
        zero_mae = mean(abs(r["actual_pct"]) for r in recent)
        status = "insufficient-samples" if len(recent) < min_samples else "degraded" if mae > zero_mae * 1.1 else "ok"
        reports.append({"model": model, "horizon_days": horizon, "samples": len(recent), "status": status,
                        "mae_pct": mae, "zero_mae_pct": zero_mae,
                        "direction_accuracy": mean((r["predicted_pct"] > 0) == (r["actual_pct"] > 0) for r in recent)})
    return reports


def run_monitor(root: Path, store, *, min_samples=20, disable_degraded=False, now=None):
    from .registry import active_models, deactivate_model
    now = now or datetime.now(timezone.utc)
    if isinstance(min_samples, bool) or not isinstance(min_samples, int) or min_samples < 3:
        raise ValueError("min_samples must be an integer >=3")
    expected = latest_completed_session(now).isoformat()
    active = active_models(root)
    archives = list((root / "predictions").glob("*.json"))
    symbols, errors = set(active), []
    for path in archives:
        try:
            symbols.add(json.loads(path.read_text(encoding="utf-8"))["symbol"])
        except (ValueError, KeyError) as error:
            errors.append({"file": path.name, "error": str(error)})
    results = []
    benchmark = store.list_daily_bars("SPY", 5000)
    for symbol in sorted(symbols):
        try:
            stock = store.list_daily_bars(symbol, 5000)
            cutoff = max((str(b.get("trade_date") or b.get("date")) for b in stock), default="")
            benchmark_cutoff = max((str(b.get("trade_date") or b.get("date")) for b in benchmark), default="")
            if cutoff > expected or benchmark_cutoff > expected:
                raise ValueError("stored bars include an incomplete or future session")
            if symbol in active and cutoff == expected and benchmark_cutoff == expected:
                archive = root / "predictions" / f"forward-{symbol}-{active[symbol]}-{cutoff}.json"
                if not archive.exists():
                    prediction = registered_prediction(root, symbol, stock, benchmark)
                    write_json(archive, {"symbol": symbol, "recorded_at": now.isoformat(), "prediction": prediction})
            report = score_archived_predictions(root, symbol, stock, benchmark)
            metrics = summarize(report["observations"], min_samples)
            stale = cutoff < expected or benchmark_cutoff < expected
            degraded = any(m["model"] == active.get(symbol) and m["status"] == "degraded" for m in metrics)
            action = None
            if disable_degraded and degraded and not stale:
                action = deactivate_model(root, symbol, active[symbol], "forward MAE exceeded zero-excess baseline by >10%")
            results.append({"symbol": symbol, "data_cutoff": cutoff, "expected_session": expected,
                            "data_stale": stale, "metrics": metrics, "action": action,
                            "pending": report["pending"], "retrospective_excluded": report["retrospective_excluded"]})
        except Exception as error:
            errors.append({"symbol": symbol, "error": str(error)})
    result = {"at": now.isoformat(), "status": "error" if errors else "attention" if any(
        r["data_stale"] or any(m["status"] == "degraded" for m in r["metrics"]) for r in results) else "ok",
        "results": results, "errors": errors,
        "note": "Non-overlapping outcomes; 10% degradation policy is operational, not a significance test."}
    write_json(root / "monitoring" / (uuid4().hex + ".json"), result)
    write_json(root / "monitoring" / "latest.json", result)
    return result
