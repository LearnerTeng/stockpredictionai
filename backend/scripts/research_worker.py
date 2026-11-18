"""Incrementally snapshot and embed stored news. Run one or more PostgreSQL workers."""
import argparse
import logging
from pathlib import Path
import sys
from time import sleep

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database.session import create_database_engine, session_factory
from retrieval.store import RetrievalStore
from runtime_status import heartbeat


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--snapshot-only", action="store_true")
    parser.add_argument("--news-only", action="store_true", help="Process selected news models without embedding calls")
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
            from sentiment.model_lines import NewsModelLines
            NewsModelLines(store.sessions).retry_failed()
        while True:
            try:
                snapshots = store.sync()
                # 仅新闻模式仍保存来源快照，但跳过向量嵌入队列和调用。
                # News-only mode still saves source snapshots and skips embedding queues and calls.
                queued = store.enqueue() if not args.news_only else 0
                result = {} if args.snapshot_only or args.news_only else store.process(args.batch_size)
                if not args.snapshot_only:
                    import json
                    from database.models import AppSetting
                    from sentiment.model_lines import NewsModelLines
                    with store.sessions() as session:
                        setting = session.get(AppSetting, 'news_model_enabled')
                        enabled = json.loads(setting.value_json) if setting else []
                    news = NewsModelLines(store.sessions)
                    news_queued = news.enqueue(enabled) if enabled else 0
                    news_result = news.process(args.batch_size)
                    logging.info('news_queued=%s news_result=%s', news_queued, news_result)
                    result['failed'] = result.get('failed', 0) + news_result['failed']
                logging.info("snapshots=%s queued=%s result=%s", snapshots, queued, result)
                code = 1 if result.get("failed") else 0
                heartbeat(success=not code, error="Job failures; see research and news queues" if code else None)
            except Exception as error:
                logging.error("research worker failed: %s", type(error).__name__)
                code = 1
                heartbeat(success=False, error=type(error).__name__)
            if args.once:
                return code
            sleep(args.interval)
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
