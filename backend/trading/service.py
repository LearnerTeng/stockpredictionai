from __future__ import annotations

import os
from pathlib import Path

from .store import DEFAULT_DB_PATH, TradingStore


DB_PATH = Path(os.getenv("TRADING_DB_PATH", str(DEFAULT_DB_PATH)))
store = TradingStore(DB_PATH)
store.init_schema()
