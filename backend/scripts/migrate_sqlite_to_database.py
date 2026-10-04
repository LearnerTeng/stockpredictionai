from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from pathlib import Path
import sqlite3
import sys
from typing import Any

from sqlalchemy import select

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database.models import (  # noqa: E402
    AppSetting,
    DailyBar,
    IngestionRun,
    Instrument,
    PaperOrder,
    PerformancePoint,
    Portfolio,
    Position,
    Recommendation,
    StockPreference,
)
from database.session import create_database_engine, session_factory  # noqa: E402
from market_data.store import infer_market  # noqa: E402


def _datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _optional_datetime(value: Any) -> datetime | None:
    return _datetime(value) if value else None


def _rows(path: Path, table: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        found = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        if found is None:
            return []
        return [dict(row) for row in connection.execute(f'SELECT * FROM "{table}"').fetchall()]


def migrate(market_path: Path, trading_path: Path, database_url: str) -> dict[str, int]:
    sessions = session_factory(create_database_engine(database_url))
    counts: dict[str, int] = {}

    with sessions.begin() as session:
        instrument_rows = _rows(market_path, "stock_universe")
        bar_rows = _rows(market_path, "daily_bars")
        known_symbols = {row["symbol"] for row in instrument_rows}
        now = datetime.now(timezone.utc)
        for symbol in sorted({row["symbol"] for row in bar_rows} - known_symbols):
            market = infer_market(symbol)
            instrument_rows.append(
                {
                    "symbol": symbol,
                    "name": None,
                    "market": market,
                    "exchange": None,
                    "sector": None,
                    "status": "active",
                    "recommendation_score": None,
                    "notes": "Recovered from orphaned legacy daily bars during migration",
                    "last_refreshed_at": None,
                    "created_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                }
            )
        for row in instrument_rows:
            market = row.get("market") or infer_market(row["symbol"])
            session.merge(
                Instrument(
                    symbol=row["symbol"],
                    name=row.get("name"),
                    market=market,
                    exchange=row.get("exchange"),
                    sector=row.get("sector"),
                    currency={"US": "USD", "JP": "JPY", "HK": "HKD"}.get(market, "USD"),
                    status=row.get("status") or "candidate",
                    recommendation_score=row.get("recommendation_score"),
                    notes=row.get("notes"),
                    last_refreshed_at=_optional_datetime(row.get("last_refreshed_at")),
                    created_at=_datetime(row["created_at"]),
                    updated_at=_datetime(row["updated_at"]),
                )
            )
        counts["instruments"] = len(instrument_rows)

        batch_rows = _rows(market_path, "import_batches")
        known_batch_ids = {row["id"] for row in batch_rows}
        import json

        for row in batch_rows:
            session.merge(
                IngestionRun(
                    id=row["id"],
                    source=row["source"],
                    status=row["status"],
                    requested_symbols=json.loads(row.get("requested_symbols_json") or "[]"),
                    imported_symbols=json.loads(row.get("imported_symbols_json") or "[]"),
                    records_received=int(row.get("records_inserted") or 0),
                    records_written=int(row.get("records_inserted") or 0),
                    attempts=1 if row["status"] == "completed" else 0,
                    max_attempts=3,
                    request_payload={"migrated_from": "sqlite"},
                    errors=[],
                    notes=row.get("notes"),
                    created_at=_datetime(row["created_at"]),
                    updated_at=_datetime(row["updated_at"]),
                    finished_at=_optional_datetime(row.get("finished_at")),
                )
            )
        counts["ingestion_runs"] = len(batch_rows)

        session.flush()
        for row in bar_rows:
            existing = session.scalar(
                select(DailyBar).where(
                    DailyBar.symbol == row["symbol"],
                    DailyBar.trade_date == date.fromisoformat(row["trade_date"]),
                )
            )
            values = {
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row["close"],
                "adj_close": row.get("adj_close"),
                "volume": row.get("volume"),
                "source": row["source"],
                "ingestion_run_id": row.get("batch_id") if row.get("batch_id") in known_batch_ids else None,
                "updated_at": _datetime(row["created_at"]),
            }
            if existing is None:
                session.add(
                    DailyBar(
                        symbol=row["symbol"],
                        trade_date=date.fromisoformat(row["trade_date"]),
                        created_at=_datetime(row["created_at"]),
                        **values,
                    )
                )
            else:
                for key, value in values.items():
                    setattr(existing, key, value)
        counts["daily_bars"] = len(bar_rows)

        for row in _rows(trading_path, "recommendations"):
            session.merge(
                Recommendation(
                    symbol=row["symbol"], name=row["name"], score=row["score"], stance=row["stance"],
                    horizon=row["horizon"], latest_price=row["latest_price"],
                    projected_return_pct=row["projected_return_pct"], components_json=row["components_json"],
                    thesis=row["thesis"], risks_json=row["risks_json"], source=row["source"],
                    generated_at=_datetime(row["generated_at"]), updated_at=_datetime(row["updated_at"]),
                )
            )
        counts["recommendations"] = len(_rows(trading_path, "recommendations"))

        portfolio_rows = _rows(trading_path, "portfolios")
        for row in portfolio_rows:
            session.merge(
                Portfolio(
                    id=row["id"], name=row["name"], mode=row["mode"], cash=row["cash"],
                    benchmark_symbol=row["benchmark_symbol"], created_at=_datetime(row["created_at"]),
                    updated_at=_datetime(row["updated_at"]),
                )
            )
        counts["portfolios"] = len(portfolio_rows)
        session.flush()

        position_rows = _rows(trading_path, "positions")
        for row in position_rows:
            entity = session.scalar(select(Position).where(Position.portfolio_id == row["portfolio_id"], Position.symbol == row["symbol"]))
            if entity is None:
                entity = Position(portfolio_id=row["portfolio_id"], symbol=row["symbol"])
                session.add(entity)
            entity.name = row["name"]
            entity.quantity = row["quantity"]
            entity.average_cost = row["average_cost"]
            entity.last_price = row["last_price"]
            entity.updated_at = _datetime(row["updated_at"])
        counts["positions"] = len(position_rows)

        performance_rows = _rows(trading_path, "performance_points")
        for row in performance_rows:
            trade_date = date.fromisoformat(row["trade_date"])
            entity = session.scalar(select(PerformancePoint).where(PerformancePoint.portfolio_id == row["portfolio_id"], PerformancePoint.trade_date == trade_date))
            if entity is None:
                entity = PerformancePoint(portfolio_id=row["portfolio_id"], trade_date=trade_date)
                session.add(entity)
            entity.portfolio_value = row["portfolio_value"]
            entity.benchmark_value = row["benchmark_value"]
        counts["performance_points"] = len(performance_rows)

        order_rows = _rows(trading_path, "paper_orders")
        for row in order_rows:
            session.merge(
                PaperOrder(
                    id=row["id"], client_order_id=row["client_order_id"], portfolio_id=row["portfolio_id"],
                    symbol=row["symbol"], side=row["side"], quantity=row["quantity"], order_type=row["order_type"],
                    limit_price=row.get("limit_price"), estimated_price=row["estimated_price"],
                    estimated_notional=row["estimated_notional"], status=row["status"],
                    risk_result_json=row["risk_result_json"], filled_price=row.get("filled_price"),
                    error_message=row.get("error_message"), created_at=_datetime(row["created_at"]),
                    updated_at=_datetime(row["updated_at"]), confirmed_at=_optional_datetime(row.get("confirmed_at")),
                )
            )
        counts["paper_orders"] = len(order_rows)

        preference_rows = _rows(trading_path, "stock_preferences")
        for row in preference_rows:
            session.merge(
                StockPreference(
                    symbol=row["symbol"], wanted=bool(row["wanted"]), created_at=_datetime(row["created_at"]),
                    updated_at=_datetime(row["updated_at"]),
                )
            )
        counts["stock_preferences"] = len(preference_rows)

        setting_rows = _rows(trading_path, "app_settings")
        for row in setting_rows:
            session.merge(AppSetting(key=row["key"], value_json=row["value_json"], updated_at=_datetime(row["updated_at"])))
        counts["app_settings"] = len(setting_rows)

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate legacy SQLite data into the unified database")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--market-db", type=Path, default=BACKEND_ROOT / "market_data" / "storage" / "market_data.db")
    parser.add_argument("--trading-db", type=Path, default=BACKEND_ROOT / "trading" / "storage" / "trading.db")
    args = parser.parse_args()
    result = migrate(args.market_db, args.trading_db, args.database_url)
    for table, count in sorted(result.items()):
        print(f"{table}: {count}")


if __name__ == "__main__":
    main()
