from __future__ import annotations

import argparse
from pathlib import Path
import sys
from time import sleep

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from market_data.ingestion import IngestionService  # noqa: E402
from market_data.service import store  # noqa: E402
from stock_ai.data import YahooFinanceDataProvider  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run queued market-data ingestion jobs")
    parser.add_argument("--once", action="store_true", help="Process the current queue and exit")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    args = parser.parse_args()
    service = IngestionService(store, YahooFinanceDataProvider(), max_workers=1)
    while True:
        job_ids = service.recover_pending(20)
        for job_id in job_ids:
            future = service._futures[job_id]
            future.result()
        if args.once:
            return
        sleep(max(args.poll_seconds, 0.5))


if __name__ == "__main__":
    main()
