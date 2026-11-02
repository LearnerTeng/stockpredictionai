"""Point-in-time imports, portfolio replay and forward monitoring."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    master = sub.add_parser("import-master", help="Import trusted security aliases and historical memberships")
    master.add_argument("input", type=Path)
    replay = sub.add_parser("backtest", help="Replay a frozen multi-asset JSON dataset")
    replay.add_argument("input", type=Path)
    replay.add_argument("--output", type=Path, required=True)
    observe = sub.add_parser("monitor", help="Score matured predictions and write per-model monitoring reports")
    observe.add_argument("--registry", type=Path, default=Path(os.getenv("MODEL_REGISTRY_DIR", "backend/storage/research")))
    observe.add_argument("--min-samples", type=int, default=20)
    observe.add_argument("--disable-degraded", action="store_true")
    ledger = sub.add_parser("reconcile", help="Compare SQL paper cash ledger and optional operator statement")
    ledger.add_argument("--portfolio", default="primary")
    ledger.add_argument("--statement", type=Path)
    args = parser.parse_args()
    if args.command == "backtest":
        from stock_ai.portfolio_backtest import PortfolioBacktestConfig, run_portfolio_backtest
        from stock_ai.research import write_json
        dataset = json.loads(args.input.read_text(encoding="utf-8"))
        result = run_portfolio_backtest(dataset, PortfolioBacktestConfig(**dataset.get("config", {})))
        write_json(args.output, result)
        print(json.dumps(result["metrics"], indent=2))
    elif args.command in {"import-master", "reconcile"}:
        from database.session import configured_database_url
        from database.market_store import SqlAlchemyMarketDataStore
        from market_data.point_in_time import import_security_master
        url = configured_database_url()
        if not url:
            parser.error("DATABASE_URL is required; run Alembic first")
        store = SqlAlchemyMarketDataStore(url)
        try:
            if args.command == "import-master":
                import_security_master(store.sessions, json.loads(args.input.read_text(encoding="utf-8")))
                print("Security master imported.")
            else:
                from trading.ledger import reconcile
                statement = json.loads(args.statement.read_text(encoding="utf-8")) if args.statement else None
                report = reconcile(store.sessions, args.portfolio, statement)
                print(json.dumps(report, indent=2))
                return 1 if report["status"] == "mismatch" else 0
        finally:
            store.engine.dispose()
    else:
        from market_data.service import store
        from stock_ai.forward_monitor import run_monitor
        print(json.dumps(run_monitor(args.registry, store, min_samples=args.min_samples,
                                     disable_degraded=args.disable_degraded), indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
