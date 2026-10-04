from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from time import sleep

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database.session import configured_database_url  # noqa: E402
from sentiment.service import NewsIngestionService  # noqa: E402
from sentiment.store import SentimentStore  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run scheduled news sentiment ingestion")
    parser.add_argument("--once", action="store_true", help="Run/recover one cycle and exit")
    parser.add_argument("--backfill", action="store_true", help="Queue a best-effort two-year backfill")
    parser.add_argument("--poll-seconds", type=float, default=60.0)
    args = parser.parse_args()
    database_url = configured_database_url()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for the news worker")
    store = SentimentStore(database_url)
    service = NewsIngestionService(store)

    while True:
        pending = store.pending_jobs(10)
        if not pending:
            settings = store.settings(smtp_configured=service.mailer.configured)
            latest = store.latest_completed_job()
            latest_finished = datetime.fromisoformat(latest["finished_at"]) if latest and latest.get("finished_at") else None
            due = latest_finished is None or datetime.now(timezone.utc) - latest_finished >= timedelta(minutes=int(settings["interval_minutes"]))
            if args.backfill:
                pending = [service.enqueue(mode="backfill")]
                args.backfill = False
            elif settings.get("enabled") and due:
                pending = [service.enqueue(mode="incremental")]
        for job in pending:
            service.run(job["id"])

        now_jst = datetime.now(timezone(timedelta(hours=9)))
        digest_time = store.settings().get("digest_time", "08:00")
        if now_jst.strftime("%H:%M") >= digest_time:
            try:
                service.send_daily_digest()
            except Exception:
                pass
        try:
            service.retry_failed_alerts()
        except Exception:
            pass
        if args.once:
            return
        sleep(max(args.poll_seconds, 5.0))


if __name__ == "__main__":
    main()
