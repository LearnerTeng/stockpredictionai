from __future__ import annotations

from contextlib import closing
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sqlite3
from threading import Lock
from typing import Any
from uuid import uuid4

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "storage" / "market_data.db"
VALID_MARKETS = {"US", "JP", "HK"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_symbol(value: str) -> str:
    symbol = str(value or "").strip().upper()
    if not symbol:
        raise ValueError("symbol is required")
    if len(symbol) > 16:
        raise ValueError("symbol must be 16 characters or fewer")
    return symbol


def normalize_market(value: Any) -> str:
    market = str(value or "US").strip().upper()
    if market not in VALID_MARKETS:
        raise ValueError("market must be one of: US, JP, HK")
    return market


def normalize_market_symbol(value: Any, market: Any) -> str:
    normalized_market = normalize_market(market)
    raw = normalize_symbol(value)
    if normalized_market == "JP":
        return raw if raw.endswith(".T") else f"{raw}.T"
    if normalized_market == "HK":
        code = raw[:-3] if raw.endswith(".HK") else raw
        if code.isdigit():
            code = code.zfill(4)
        return f"{code}.HK"
    return raw


def infer_market(symbol: Any) -> str:
    normalized = normalize_symbol(symbol)
    if normalized.endswith(".T"):
        return "JP"
    if normalized.endswith(".HK"):
        return "HK"
    return "US"


def normalize_trade_date(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()

    text = str(value or "").strip()
    if not text:
        raise ValueError("trade_date is required")

    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as err:
        raise ValueError("trade_date must be an ISO date like 2026-04-06") from err


class MarketDataStore:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path or DEFAULT_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        with self._lock:
            with closing(self._connect()) as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS stock_universe (
                        symbol TEXT PRIMARY KEY,
                        name TEXT,
                        market TEXT NOT NULL DEFAULT 'US',
                        exchange TEXT,
                        sector TEXT,
                        status TEXT NOT NULL DEFAULT 'candidate',
                        recommendation_score REAL,
                        notes TEXT,
                        last_refreshed_at TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS import_batches (
                        id TEXT PRIMARY KEY,
                        source TEXT NOT NULL,
                        status TEXT NOT NULL,
                        requested_symbols_json TEXT NOT NULL,
                        imported_symbols_json TEXT,
                        records_inserted INTEGER NOT NULL DEFAULT 0,
                        notes TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        finished_at TEXT
                    );

                    CREATE TABLE IF NOT EXISTS daily_bars (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        symbol TEXT NOT NULL,
                        trade_date TEXT NOT NULL,
                        open REAL,
                        high REAL,
                        low REAL,
                        close REAL NOT NULL,
                        adj_close REAL,
                        volume INTEGER,
                        source TEXT NOT NULL,
                        batch_id TEXT,
                        created_at TEXT NOT NULL,
                        UNIQUE(symbol, trade_date),
                        FOREIGN KEY(symbol) REFERENCES stock_universe(symbol),
                        FOREIGN KEY(batch_id) REFERENCES import_batches(id)
                    );

                    CREATE INDEX IF NOT EXISTS idx_daily_bars_symbol_date
                    ON daily_bars(symbol, trade_date DESC);

                    CREATE INDEX IF NOT EXISTS idx_import_batches_status
                    ON import_batches(status, created_at DESC);
                    """
                )
                columns = {row["name"] for row in conn.execute("PRAGMA table_info(stock_universe)").fetchall()}
                if "market" not in columns:
                    conn.execute("ALTER TABLE stock_universe ADD COLUMN market TEXT NOT NULL DEFAULT 'US'")
                if "last_refreshed_at" not in columns:
                    conn.execute("ALTER TABLE stock_universe ADD COLUMN last_refreshed_at TEXT")
                conn.execute(
                    """
                    UPDATE stock_universe
                    SET market = CASE
                        WHEN symbol LIKE '%.T' THEN 'JP'
                        WHEN symbol LIKE '%.HK' THEN 'HK'
                        ELSE 'US'
                    END
                    WHERE market IS NULL OR market = '' OR market NOT IN ('US', 'JP', 'HK')
                    """
                )
                conn.commit()

    def universe_summary(self) -> dict[str, Any]:
        with self._lock:
            with closing(self._connect()) as conn:
                summary = conn.execute(
                    """
                    SELECT
                        COUNT(*) AS symbols_count,
                        COALESCE(SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END), 0) AS active_symbols_count
                    FROM stock_universe
                    """
                ).fetchone()
                bars = conn.execute("SELECT COUNT(*) AS bars_count FROM daily_bars").fetchone()
                batches = conn.execute("SELECT COUNT(*) AS batches_count FROM import_batches").fetchone()

        return {
            "db_path": str(self.db_path),
            "symbols_count": summary["symbols_count"],
            "active_symbols_count": summary["active_symbols_count"],
            "bars_count": bars["bars_count"],
            "batches_count": batches["batches_count"],
        }

    def upsert_symbols(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not items:
            raise ValueError("symbols must contain at least one item")

        now = utc_now_iso()
        normalized: list[dict[str, Any]] = []
        for item in items:
            symbol = normalize_symbol(item.get("symbol"))
            normalized.append(
                {
                    "symbol": symbol,
                    "name": str(item.get("name", "") or "").strip() or None,
                    "market": normalize_market(item.get("market") or infer_market(symbol)),
                    "exchange": str(item.get("exchange", "") or "").strip() or None,
                    "sector": str(item.get("sector", "") or "").strip() or None,
                    "status": str(item.get("status", "candidate") or "candidate").strip().lower(),
                    "recommendation_score": float(item["recommendation_score"])
                    if item.get("recommendation_score") is not None
                    else None,
                    "notes": str(item.get("notes", "") or "").strip() or None,
                }
            )

        with self._lock:
            with closing(self._connect()) as conn:
                for item in normalized:
                    existing = conn.execute(
                        "SELECT created_at FROM stock_universe WHERE symbol = ?",
                        (item["symbol"],),
                    ).fetchone()
                    created_at = existing["created_at"] if existing else now
                    conn.execute(
                        """
                        INSERT INTO stock_universe (
                            symbol, name, market, exchange, sector, status, recommendation_score,
                            notes, last_refreshed_at, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                        ON CONFLICT(symbol) DO UPDATE SET
                            name = COALESCE(excluded.name, stock_universe.name),
                            market = excluded.market,
                            exchange = COALESCE(excluded.exchange, stock_universe.exchange),
                            sector = COALESCE(excluded.sector, stock_universe.sector),
                            status = excluded.status,
                            recommendation_score = COALESCE(excluded.recommendation_score, stock_universe.recommendation_score),
                            notes = COALESCE(excluded.notes, stock_universe.notes),
                            updated_at = excluded.updated_at
                        """,
                        (
                            item["symbol"],
                            item["name"],
                            item["market"],
                            item["exchange"],
                            item["sector"],
                            item["status"],
                            item["recommendation_score"],
                            item["notes"],
                            created_at,
                            now,
                        ),
                    )
                conn.commit()

        return self.list_symbols()

    def list_symbols(self) -> list[dict[str, Any]]:
        with self._lock:
            with closing(self._connect()) as conn:
                rows = conn.execute(
                    """
                    SELECT symbol, name, market, exchange, sector, status, recommendation_score,
                           notes, last_refreshed_at, created_at, updated_at
                    FROM stock_universe
                    ORDER BY
                        CASE status
                            WHEN 'active' THEN 0
                            WHEN 'candidate' THEN 1
                            ELSE 2
                        END,
                        COALESCE(recommendation_score, -999999) DESC,
                        symbol ASC
                    """
                ).fetchall()

        return [dict(row) for row in rows]

    def get_symbol(self, symbol: str) -> dict[str, Any]:
        normalized = normalize_symbol(symbol)
        with self._lock:
            with closing(self._connect()) as conn:
                row = conn.execute(
                    """
                    SELECT symbol, name, market, exchange, sector, status, recommendation_score,
                           notes, last_refreshed_at, created_at, updated_at
                    FROM stock_universe WHERE symbol = ?
                    """,
                    (normalized,),
                ).fetchone()
        if row is None:
            raise ValueError("symbol not found")
        return dict(row)

    def update_symbol_metadata(self, symbol: str, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_symbol(symbol)
        now = utc_now_iso()
        allowed = {"name", "market", "exchange", "sector", "notes"}
        assignments: list[str] = []
        values: list[Any] = []
        for key in allowed:
            if key not in payload:
                continue
            value = normalize_market(payload[key]) if key == "market" else str(payload[key] or "").strip() or None
            assignments.append(f"{key} = ?")
            values.append(value)
        if not assignments:
            raise ValueError("at least one metadata field is required")
        assignments.append("updated_at = ?")
        values.extend([now, normalized])
        with self._lock:
            with closing(self._connect()) as conn:
                cursor = conn.execute(
                    f"UPDATE stock_universe SET {', '.join(assignments)} WHERE symbol = ?",
                    values,
                )
                if cursor.rowcount == 0:
                    conn.execute(
                        """
                        INSERT INTO stock_universe (
                            symbol, name, market, exchange, sector, status, recommendation_score,
                            notes, last_refreshed_at, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, 'candidate', NULL, ?, NULL, ?, ?)
                        """,
                        (
                            normalized,
                            str(payload.get("name", "") or "").strip() or None,
                            normalize_market(payload.get("market") or infer_market(normalized)),
                            str(payload.get("exchange", "") or "").strip() or None,
                            str(payload.get("sector", "") or "").strip() or None,
                            str(payload.get("notes", "") or "").strip() or None,
                            now,
                            now,
                        ),
                    )
                conn.commit()
        return self.get_symbol(normalized)

    def list_symbol_snapshots(self) -> list[dict[str, Any]]:
        with self._lock:
            with closing(self._connect()) as conn:
                rows = conn.execute(
                    """
                    WITH ranked AS (
                        SELECT symbol, trade_date, close,
                               ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY trade_date DESC) AS rank
                        FROM daily_bars
                    )
                    SELECT u.symbol, u.name, u.market, u.exchange, u.sector, u.status,
                           u.recommendation_score, u.notes, u.last_refreshed_at, u.updated_at,
                           MAX(CASE WHEN r.rank = 1 THEN r.trade_date END) AS latest_trade_date,
                           MAX(CASE WHEN r.rank = 1 THEN r.close END) AS latest_price,
                           MAX(CASE WHEN r.rank = 2 THEN r.close END) AS previous_close
                    FROM stock_universe u
                    LEFT JOIN ranked r ON r.symbol = u.symbol AND r.rank <= 2
                    GROUP BY u.symbol
                    ORDER BY u.symbol
                    """
                ).fetchall()
        return [dict(row) for row in rows]

    def create_import_batch(self, symbols: list[str], source: str, notes: str | None = None) -> dict[str, Any]:
        normalized_symbols = [normalize_symbol(symbol) for symbol in symbols]
        if not normalized_symbols:
            raise ValueError("symbols must contain at least one symbol")

        batch_id = uuid4().hex
        now = utc_now_iso()
        source_name = str(source or "").strip() or "manual"

        with self._lock:
            with closing(self._connect()) as conn:
                conn.execute(
                    """
                    INSERT INTO import_batches (
                        id, source, status, requested_symbols_json, imported_symbols_json,
                        records_inserted, notes, created_at, updated_at, finished_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        batch_id,
                        source_name,
                        "planned",
                        json.dumps(normalized_symbols, ensure_ascii=True),
                        json.dumps([], ensure_ascii=True),
                        0,
                        notes,
                        now,
                        now,
                        None,
                    ),
                )
                conn.commit()

        return self.get_import_batch(batch_id)

    def list_import_batches(self) -> list[dict[str, Any]]:
        with self._lock:
            with closing(self._connect()) as conn:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM import_batches
                    ORDER BY created_at DESC
                    """
                ).fetchall()

        return [self._serialize_batch(row) for row in rows]

    def get_import_batch(self, batch_id: str) -> dict[str, Any]:
        with self._lock:
            with closing(self._connect()) as conn:
                row = conn.execute(
                    "SELECT * FROM import_batches WHERE id = ?",
                    (batch_id,),
                ).fetchone()

        if row is None:
            raise ValueError("batch not found")
        return self._serialize_batch(row)

    def ingest_daily_bars(
        self,
        symbol: str,
        bars: list[dict[str, Any]],
        *,
        source: str = "manual",
        batch_id: str | None = None,
    ) -> dict[str, Any]:
        normalized_symbol = normalize_symbol(symbol)
        if not bars:
            raise ValueError("bars must contain at least one row")

        normalized_bars: list[dict[str, Any]] = []
        imported_dates: list[str] = []
        created_at = utc_now_iso()
        for bar in bars:
            trade_date = normalize_trade_date(bar.get("date") or bar.get("trade_date"))
            close = float(bar.get("close"))
            normalized_bars.append(
                {
                    "trade_date": trade_date,
                    "open": float(bar["open"]) if bar.get("open") is not None else None,
                    "high": float(bar["high"]) if bar.get("high") is not None else None,
                    "low": float(bar["low"]) if bar.get("low") is not None else None,
                    "close": close,
                    "adj_close": float(bar["adj_close"]) if bar.get("adj_close") is not None else None,
                    "volume": int(bar["volume"]) if bar.get("volume") is not None else None,
                }
            )
            imported_dates.append(trade_date)

        with self._lock:
            with closing(self._connect()) as conn:
                existing_symbol = conn.execute(
                    "SELECT symbol FROM stock_universe WHERE symbol = ?",
                    (normalized_symbol,),
                ).fetchone()
                if existing_symbol is None:
                    conn.execute(
                        """
                        INSERT INTO stock_universe (
                            symbol, name, market, exchange, sector, status, recommendation_score,
                            notes, last_refreshed_at, created_at, updated_at
                        ) VALUES (?, NULL, ?, NULL, NULL, 'active', NULL,
                                  'Auto-created by daily bar ingest', ?, ?, ?)
                        """,
                        (normalized_symbol, infer_market(normalized_symbol), created_at, created_at, created_at),
                    )

                inserted = 0
                for bar in normalized_bars:
                    cursor = conn.execute(
                        """
                        INSERT INTO daily_bars (
                            symbol, trade_date, open, high, low, close, adj_close, volume, source, batch_id, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(symbol, trade_date) DO UPDATE SET
                            open = excluded.open,
                            high = excluded.high,
                            low = excluded.low,
                            close = excluded.close,
                            adj_close = excluded.adj_close,
                            volume = excluded.volume,
                            source = excluded.source,
                            batch_id = excluded.batch_id
                        """,
                        (
                            normalized_symbol,
                            bar["trade_date"],
                            bar["open"],
                            bar["high"],
                            bar["low"],
                            bar["close"],
                            bar["adj_close"],
                            bar["volume"],
                            source,
                            batch_id,
                            created_at,
                        ),
                    )
                    inserted += 1 if cursor.rowcount != 0 else 0

                if batch_id:
                    batch = conn.execute(
                        "SELECT imported_symbols_json, records_inserted FROM import_batches WHERE id = ?",
                        (batch_id,),
                    ).fetchone()
                    if batch is not None:
                        imported_symbols = set(json.loads(batch["imported_symbols_json"] or "[]"))
                        imported_symbols.add(normalized_symbol)
                        now = utc_now_iso()
                        conn.execute(
                            """
                            UPDATE import_batches
                            SET status = ?, imported_symbols_json = ?, records_inserted = ?, updated_at = ?, finished_at = ?
                            WHERE id = ?
                            """,
                            (
                                "completed",
                                json.dumps(sorted(imported_symbols), ensure_ascii=True),
                                int(batch["records_inserted"] or 0) + len(normalized_bars),
                                now,
                                now,
                                batch_id,
                            ),
                        )
                conn.execute(
                    "UPDATE stock_universe SET status = 'active', last_refreshed_at = ?, updated_at = ? WHERE symbol = ?",
                    (created_at, created_at, normalized_symbol),
                )
                conn.commit()

        return {
            "symbol": normalized_symbol,
            "source": source,
            "batch_id": batch_id,
            "rows_received": len(normalized_bars),
            "trade_dates": imported_dates,
        }

    def list_daily_bars(self, symbol: str, limit: int = 60) -> list[dict[str, Any]]:
        normalized_symbol = normalize_symbol(symbol)
        normalized_limit = min(max(int(limit), 1), 500)
        with self._lock:
            with closing(self._connect()) as conn:
                rows = conn.execute(
                    """
                    SELECT symbol, trade_date, open, high, low, close, adj_close, volume, source, batch_id, created_at
                    FROM daily_bars
                    WHERE symbol = ?
                    ORDER BY trade_date DESC
                    LIMIT ?
                    """,
                    (normalized_symbol, normalized_limit),
                ).fetchall()

        return [dict(row) for row in rows]

    def _serialize_batch(self, row: sqlite3.Row) -> dict[str, Any]:
        requested = json.loads(row["requested_symbols_json"] or "[]")
        imported = json.loads(row["imported_symbols_json"] or "[]")
        return {
            "id": row["id"],
            "source": row["source"],
            "status": row["status"],
            "requested_symbols": requested,
            "imported_symbols": imported,
            "records_inserted": row["records_inserted"],
            "notes": row["notes"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "finished_at": row["finished_at"],
        }
