from __future__ import annotations

import os
from pathlib import Path

from database.market_store import SqlAlchemyMarketDataStore
from database.session import configured_database_url
from .store import DEFAULT_DB_PATH, MarketDataStore

DATABASE_URL = configured_database_url()
DB_PATH = Path(os.getenv("STOCK_DATA_DB_PATH", str(DEFAULT_DB_PATH)))
store = SqlAlchemyMarketDataStore(DATABASE_URL) if DATABASE_URL else MarketDataStore(DB_PATH)
store.init_schema()
