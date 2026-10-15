"""Run forward monitoring using refreshed local bars. One process per registry."""
import argparse
import logging
import os
from pathlib import Path
import sys
from time import sleep

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stock_ai.forward_monitor import run_monitor
from stock_ai.research import write_json
from datetime import datetime, timezone


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=Path(os.getenv("MODEL_REGISTRY_DIR", "backend/storage/research")))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=3600)
    parser.add_argument("--disable-degraded", action="store_true")
    args = parser.parse_args()
    if args.interval_seconds < 60:
        parser.error("interval must be >=60 seconds")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from market_data.service import store
    while True:
        try:
            report = run_monitor(args.registry, store, disable_degraded=args.disable_degraded)
            logging.info("forward_monitor status=%s symbols=%s errors=%s", report["status"], len(report["results"]), len(report["errors"]))
        except Exception:
            logging.exception("forward_monitor failed")
            report = {"at": datetime.now(timezone.utc).isoformat(), "status": "error", "error": "worker failed; inspect logs"}
            write_json(args.registry / "monitoring" / "latest.json", report)
        if args.once:
            return 1 if report["status"] == "error" else 0
        sleep(args.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
