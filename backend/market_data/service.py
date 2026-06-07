from __future__ import annotations

import os
from pathlib import Path

from .store import DEFAULT_DB_PATH, MarketDataStore

DB_PATH = Path(os.getenv("STOCK_DATA_DB_PATH", str(DEFAULT_DB_PATH)))
store = MarketDataStore(DB_PATH)
store.init_schema()
