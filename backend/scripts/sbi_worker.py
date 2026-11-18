"""扫描配置的 SBI 导出目录并处理待发通知。
Scan the configured SBI export folder and process its notification outbox.
"""
import argparse
import logging
import os
from pathlib import Path
import sys
from time import sleep

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database.session import create_database_engine, session_factory
from runtime_status import heartbeat
from trading.sbi import SbiImport, configured_root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    root = configured_root()
    if not root:
        while True:
            heartbeat(success=True)
            if args.once:
                return 0
            sleep(60)
    recipients = tuple(value.strip() for value in os.getenv("SBI_ALERT_RECIPIENTS", "").split(",") if value.strip())
    engine = create_database_engine()
    try:
        importer = SbiImport(session_factory(engine))
        while True:
            try:
                importer.scan(root, recipients=recipients)
                heartbeat(success=True)
                code = 0
            except Exception as error:
                detail = str(error) if isinstance(error, ValueError) else type(error).__name__
                logging.error("SBI scan: %s", detail)
                heartbeat(success=False, error=detail)
                code = 1
            if args.once:
                return code
            sleep(60)
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
