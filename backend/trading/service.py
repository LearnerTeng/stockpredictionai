from __future__ import annotations

import os
from pathlib import Path

from database.session import configured_database_url
from database.trading_store import SqlAlchemyTradingStore
from .store import DEFAULT_DB_PATH, TradingStore


DATABASE_URL = configured_database_url()
DB_PATH = Path(os.getenv("TRADING_DB_PATH", str(DEFAULT_DB_PATH)))
store = SqlAlchemyTradingStore(DATABASE_URL) if DATABASE_URL else TradingStore(DB_PATH)
store.init_schema()
