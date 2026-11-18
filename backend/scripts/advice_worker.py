"""将调度与模型执行分开运行，两者在关闭浏览器后继续运行。
Run scheduling and model execution separately so both continue after the browser closes.
"""
import argparse
import logging
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scheduler', action='store_true')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    from app import sentiment_store, market_data_store, trading_store, ingestion_service
    from advice import AdviceService
    from ai_runtime import settings
    from runtime_status import heartbeat
    if sentiment_store is None: raise RuntimeError('PostgreSQL is required')
    svc = AdviceService(sentiment_store.sessions, market_data_store, trading_store)
    last_fetch = None
    failures = 0
    while True:
        started = time.monotonic()
        interval = 2
        try:
            if args.scheduler:
                cfg = settings(svc.sessions)
                interval = cfg['interval_seconds']
                if cfg['enabled'] and (last_fetch is None or started - last_fetch >= 900):
                    symbols = set(trading_store.list_wanted_symbols())
                    for account in trading_store.list_portfolios():
                        if account.get('account_type') != 'nisa':
                            symbols.update(p['symbol'] for p in trading_store.get_portfolio(account['id'])['positions'])
                    try:
                        if symbols: ingestion_service.enqueue(sorted(symbols), range_value='1mo')
                    except Exception as error:
                        logging.warning('Incremental quotes: %s', type(error).__name__)
                    last_fetch = started
                svc.schedule()
            else:
                svc.process_one()
            failures = 0
            heartbeat(success=True)
        except Exception as error:
            logging.error('advice worker: %s', type(error).__name__)
            heartbeat(success=False, error=type(error).__name__)
            failures += 1
            interval = min(300, 5 * 2 ** min(failures - 1, 6))
            if args.once: return 1
        if args.once: break
        time.sleep(max(1, interval - (time.monotonic() - started)))

if __name__ == '__main__': raise SystemExit(main())
