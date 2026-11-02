"""Incrementally snapshot and embed stored news. Run one or more PostgreSQL workers."""
import argparse
import logging
from pathlib import Path
import sys
from time import sleep

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database.session import create_database_engine, session_factory
from retrieval.store import RetrievalStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--snapshot-only", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 100 or args.interval < 10:
        parser.error("batch-size must be 1..100 and interval >=10")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    engine = create_database_engine()
    try:
        if engine.dialect.name != "postgresql":
            parser.error("PostgreSQL is required")
        store = RetrievalStore(session_factory(engine))
        if args.retry_failed:
            store.retry_failed()
        while True:
            try:
                snapshots = store.sync()
                queued = store.enqueue()
                result = {} if args.snapshot_only else store.process(args.batch_size)
                logging.info("snapshots=%s queued=%s result=%s", snapshots, queued, result)
                code = 1 if result.get("failed") else 0
            except Exception as error:
                logging.error("research worker failed: %s", type(error).__name__)
                code = 1
            if args.once:
                return code
            sleep(args.interval)
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
