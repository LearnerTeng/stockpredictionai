"""Run with --help. Reads stored data; never submits orders or fetches the network."""
from pathlib import Path
import argparse
import json
import os
import sys

os.environ.setdefault("OMP_NUM_THREADS", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stock_ai.research import activate_run, train_run, score_archived_predictions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=Path(os.getenv("MODEL_REGISTRY_DIR", "backend/storage/research")))
    commands = parser.add_subparsers(dest="command", required=True)
    train = commands.add_parser("train", help="Snapshot data, validate 5/20-day targets and save a candidate; does not activate it")
    train.add_argument("--symbol", required=True)
    train.add_argument("--dataset", type=Path, help="Optional JSON with stock and benchmark bar arrays; otherwise read local database")
    score = commands.add_parser("score", help="Evaluate matured archived predictions against subsequently stored bars")
    score.add_argument("--symbol", required=True)
    score.add_argument("--dataset", type=Path)
    activate = commands.add_parser("activate", help="Activate a candidate passing the gate; activate an earlier run to roll back")
    activate.add_argument("run_id")
    commands.add_parser("list", help="List candidates and active selections")
    args = parser.parse_args()
    if args.command in {"train", "score"}:
        symbol = args.symbol.strip().upper()
        if args.dataset:
            data = json.loads(args.dataset.read_text(encoding="utf-8"))
            if data.get("symbol", symbol) != symbol:
                parser.error("dataset symbol differs from --symbol")
            stock, benchmark = data["stock"], data["benchmark"]
        else:
            from market_data.service import store
            stock, benchmark = store.list_daily_bars(symbol, 5000), store.list_daily_bars("SPY", 5000)
        result = (train_run if args.command == "train" else score_archived_predictions)(args.registry, symbol, stock, benchmark)
    elif args.command == "activate":
        result = activate_run(args.registry, args.run_id)
    else:
        result = {"runs": [json.loads(path.read_text(encoding="utf-8")) for path in args.registry.glob("*/manifest.json")],
                  "active": json.loads((args.registry / "active.json").read_text(encoding="utf-8")) if (args.registry / "active.json").exists() else {}}
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
