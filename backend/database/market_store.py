from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from stock_ai.contracts import normalize_bars
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from market_data.store import infer_market, normalize_market, normalize_symbol, normalize_trade_date

from .models import CorporateAction, DailyBar, IngestionRun, Instrument
from .session import create_database_engine, session_factory


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


class SqlAlchemyMarketDataStore:
    """PostgreSQL/SQLAlchemy implementation of the legacy market store contract."""

    def __init__(self, database_url: str):
        self.engine = create_database_engine(database_url)
        self.sessions = session_factory(self.engine)
        self.db_path = database_url.split("@")[-1]

    def init_schema(self) -> None:
        # Schema ownership belongs to Alembic. This method keeps the legacy
        # repository contract without creating tables during app startup.
        return None

    def universe_summary(self) -> dict[str, Any]:
        with self.sessions() as session:
            symbols = session.scalar(select(func.count()).select_from(Instrument)) or 0
            active = session.scalar(
                select(func.count()).select_from(Instrument).where(Instrument.status == "active")
            ) or 0
            bars = session.scalar(select(func.count()).select_from(DailyBar)) or 0
            batches = session.scalar(select(func.count()).select_from(IngestionRun)) or 0
        return {
            "database": "sqlalchemy",
            "symbols_count": symbols,
            "active_symbols_count": active,
            "bars_count": bars,
            "batches_count": batches,
        }

    def upsert_symbols(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not items:
            raise ValueError("symbols must contain at least one item")
        now = _now()
        with self.sessions.begin() as session:
            for item in items:
                symbol = normalize_symbol(item.get("symbol"))
                entity = session.get(Instrument, symbol)
                if entity is None:
                    entity = Instrument(
                        symbol=symbol,
                        created_at=now,
                        updated_at=now,
                        currency={"US": "USD", "JP": "JPY", "HK": "HKD"}.get(
                            normalize_market(item.get("market") or infer_market(symbol)), "USD"
                        ),
                    )
                    session.add(entity)
                entity.name = str(item.get("name", "") or "").strip() or entity.name
                entity.market = normalize_market(item.get("market") or infer_market(symbol))
                entity.exchange = str(item.get("exchange", "") or "").strip() or entity.exchange
                entity.sector = str(item.get("sector", "") or "").strip() or entity.sector
                entity.status = str(item.get("status", "candidate") or "candidate").strip().lower()
                if item.get("recommendation_score") is not None:
                    entity.recommendation_score = float(item["recommendation_score"])
                entity.notes = str(item.get("notes", "") or "").strip() or entity.notes
                entity.updated_at = now
        return self.list_symbols()

    def list_symbols(self) -> list[dict[str, Any]]:
        with self.sessions() as session:
            rows = session.scalars(
                select(Instrument).order_by(Instrument.status.asc(), Instrument.recommendation_score.desc(), Instrument.symbol)
            ).all()
            return [self._instrument(row) for row in rows]

    def get_symbol(self, symbol: str) -> dict[str, Any]:
        with self.sessions() as session:
            entity = session.get(Instrument, normalize_symbol(symbol))
            if entity is None:
                raise ValueError("symbol not found")
            return self._instrument(entity)

    def update_symbol_metadata(self, symbol: str, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_symbol(symbol)
        allowed = {"name", "market", "exchange", "sector", "notes"}
        if not any(key in payload for key in allowed):
            raise ValueError("at least one metadata field is required")
        with self.sessions.begin() as session:
            entity = session.get(Instrument, normalized)
            if entity is None:
                now = _now()
                entity = Instrument(
                    symbol=normalized,
                    market=normalize_market(payload.get("market") or infer_market(normalized)),
                    currency="USD",
                    status="candidate",
                    created_at=now,
                    updated_at=now,
                )
                session.add(entity)
            for key in allowed:
                if key not in payload:
                    continue
                value = normalize_market(payload[key]) if key == "market" else str(payload[key] or "").strip() or None
                setattr(entity, key, value)
            entity.updated_at = _now()
        return self.get_symbol(normalized)

    def list_symbol_snapshots(self) -> list[dict[str, Any]]:
        snapshots: list[dict[str, Any]] = []
        with self.sessions() as session:
            instruments = session.scalars(select(Instrument).order_by(Instrument.symbol)).all()
            for instrument in instruments:
                bars = session.scalars(
                    select(DailyBar)
                    .where(DailyBar.symbol == instrument.symbol)
                    .order_by(DailyBar.trade_date.desc())
                    .limit(2)
                ).all()
                snapshots.append(
                    {
                        **self._instrument(instrument),
                        "latest_trade_date": bars[0].trade_date.isoformat() if bars else None,
                        "latest_price": bars[0].close if bars else None,
                        "previous_close": bars[1].close if len(bars) > 1 else None,
                    }
                )
        return snapshots

    def create_import_batch(self, symbols: list[str], source: str, notes: str | None = None) -> dict[str, Any]:
        normalized = [normalize_symbol(symbol) for symbol in symbols]
        if not normalized:
            raise ValueError("symbols must contain at least one symbol")
        now = _now()
        entity = IngestionRun(
            id=uuid4().hex,
            source=str(source or "manual").strip(),
            status="planned",
            requested_symbols=normalized,
            imported_symbols=[],
            records_received=0,
            records_written=0,
            attempts=0,
            max_attempts=3,
            request_payload={},
            errors=[],
            notes=notes,
            created_at=now,
            updated_at=now,
        )
        with self.sessions.begin() as session:
            session.add(entity)
        return self.get_import_batch(entity.id)

    def list_import_batches(self) -> list[dict[str, Any]]:
        with self.sessions() as session:
            rows = session.scalars(select(IngestionRun).order_by(IngestionRun.created_at.desc())).all()
            return [self._batch(row) for row in rows]

    def get_import_batch(self, batch_id: str) -> dict[str, Any]:
        with self.sessions() as session:
            entity = session.get(IngestionRun, batch_id)
            if entity is None:
                raise ValueError("batch not found")
            return self._batch(entity)

    def update_import_batch(self, batch_id: str, **changes: Any) -> dict[str, Any]:
        aliases = {"records_inserted": "records_written"}
        allowed = {
            "status", "imported_symbols", "records_written", "records_received", "notes",
            "request_payload", "errors", "attempts", "max_attempts", "started_at", "finished_at",
        }
        with self.sessions.begin() as session:
            entity = session.get(IngestionRun, batch_id)
            if entity is None:
                raise ValueError("batch not found")
            for key, value in changes.items():
                target = aliases.get(key, key)
                if target not in allowed:
                    raise ValueError(f"unsupported import batch field: {key}")
                if target in {"started_at", "finished_at"} and isinstance(value, str):
                    value = datetime.fromisoformat(value.replace("Z", "+00:00"))
                setattr(entity, target, value)
            entity.updated_at = _now()
        return self.get_import_batch(batch_id)

    def claim_import_batch(self, batch_id: str) -> bool:
        now = _now()
        with self.sessions.begin() as session:
            result = session.execute(update(IngestionRun).where(
                IngestionRun.id == batch_id, IngestionRun.status.in_(("queued", "retrying"))
            ).values(status="running", attempts=IngestionRun.attempts + 1, started_at=now, updated_at=now))
            return result.rowcount == 1

    def list_pending_import_batches(self, limit: int = 10) -> list[dict[str, Any]]:
        with self.sessions() as session:
            rows = session.scalars(
                select(IngestionRun)
                .where(IngestionRun.status.in_(("queued", "retrying")))
                .order_by(IngestionRun.created_at)
                .limit(min(max(int(limit), 1), 100))
            ).all()
            return [self._batch(row) for row in rows]

    def ingest_corporate_actions(
        self,
        symbol: str,
        actions: list[dict[str, Any]],
        *,
        source: str = "manual",
    ) -> dict[str, Any]:
        normalized = normalize_symbol(symbol)
        with self.sessions.begin() as session:
            for action in actions:
                action_date = datetime.fromisoformat(
                    normalize_trade_date(action.get("date") or action.get("action_date"))
                ).date()
                action_type = str(action.get("type") or action.get("action_type") or "").strip().lower()
                if action_type not in {"dividend", "split"}:
                    raise ValueError("action type must be dividend or split")
                entity = session.scalar(
                    select(CorporateAction).where(
                        CorporateAction.symbol == normalized,
                        CorporateAction.action_date == action_date,
                        CorporateAction.action_type == action_type,
                    )
                )
                if entity is None:
                    entity = CorporateAction(
                        symbol=normalized,
                        action_date=action_date,
                        action_type=action_type,
                        value=float(action["value"]),
                        source=source,
                        created_at=_now(),
                    )
                    session.add(entity)
                entity.value = float(action["value"])
                entity.currency = str(action.get("currency") or "").strip() or None
                entity.source = source
                entity.payload = action.get("payload") or action
        return {"symbol": normalized, "rows_received": len(actions), "source": source}

    def ingest_daily_bars(
        self,
        symbol: str,
        bars: list[dict[str, Any]],
        *,
        source: str = "manual",
        batch_id: str | None = None,
    ) -> dict[str, Any]:
        normalized = normalize_symbol(symbol)
        bars = normalize_bars(bars)
        if not bars:
            raise ValueError("bars must contain at least one row")
        now = _now()
        dates: list[str] = []
        with self.sessions.begin() as session:
            instrument = session.get(Instrument, normalized)
            if instrument is None:
                market = infer_market(normalized)
                instrument = Instrument(
                    symbol=normalized,
                    market=market,
                    currency={"US": "USD", "JP": "JPY", "HK": "HKD"}[market],
                    status="active",
                    notes="Auto-created by daily bar ingest",
                    created_at=now,
                    updated_at=now,
                )
                session.add(instrument)
                session.flush()
            for item in bars:
                trade_date = datetime.fromisoformat(normalize_trade_date(item.get("date") or item.get("trade_date"))).date()
                dates.append(trade_date.isoformat())
                entity = session.scalar(
                    select(DailyBar).where(DailyBar.symbol == normalized, DailyBar.trade_date == trade_date)
                )
                values = {
                    "open": float(item["open"]) if item.get("open") is not None else None,
                    "high": float(item["high"]) if item.get("high") is not None else None,
                    "low": float(item["low"]) if item.get("low") is not None else None,
                    "close": float(item["close"]),
                    "adj_close": float(item["adj_close"]) if item.get("adj_close") is not None else None,
                    "volume": int(item["volume"]) if item.get("volume") is not None else None,
                }
                if entity is None:
                    entity = DailyBar(
                        symbol=normalized,
                        trade_date=trade_date,
                        source=source,
                        ingestion_run_id=batch_id,
                        created_at=now,
                        updated_at=now,
                        **values,
                    )
                    session.add(entity)
                else:
                    for key, value in values.items():
                        setattr(entity, key, value)
                    entity.source = source
                    entity.ingestion_run_id = batch_id
                    entity.updated_at = now
            instrument.status = "active"
            instrument.last_refreshed_at = now
            instrument.updated_at = now
            if batch_id:
                run = session.get(IngestionRun, batch_id)
                if run is not None:
                    run.imported_symbols = sorted(set(run.imported_symbols or []) | {normalized})
                    run.records_received += len(bars)
                    run.records_written += len(bars)
                    run.updated_at = now
        return {
            "symbol": normalized,
            "source": source,
            "batch_id": batch_id,
            "rows_received": len(bars),
            "trade_dates": dates,
        }

    def list_daily_bars(self, symbol: str, limit: int = 60) -> list[dict[str, Any]]:
        normalized = normalize_symbol(symbol)
        normalized_limit = min(max(int(limit), 1), 5000)
        with self.sessions() as session:
            rows = session.scalars(
                select(DailyBar)
                .where(DailyBar.symbol == normalized)
                .order_by(DailyBar.trade_date.desc())
                .limit(normalized_limit)
            ).all()
            return [
                {
                    "symbol": row.symbol,
                    "trade_date": row.trade_date.isoformat(),
                    "open": row.open,
                    "high": row.high,
                    "low": row.low,
                    "close": row.close,
                    "adj_close": row.adj_close,
                    "volume": row.volume,
                    "source": row.source,
                    "batch_id": row.ingestion_run_id,
                    "created_at": _iso(row.created_at),
                }
                for row in rows
            ]

    @staticmethod
    def _instrument(entity: Instrument) -> dict[str, Any]:
        return {
            "symbol": entity.symbol,
            "name": entity.name,
            "market": entity.market,
            "exchange": entity.exchange,
            "sector": entity.sector,
            "status": entity.status,
            "recommendation_score": entity.recommendation_score,
            "notes": entity.notes,
            "last_refreshed_at": _iso(entity.last_refreshed_at),
            "created_at": _iso(entity.created_at),
            "updated_at": _iso(entity.updated_at),
        }

    @staticmethod
    def _batch(entity: IngestionRun) -> dict[str, Any]:
        return {
            "id": entity.id,
            "source": entity.source,
            "status": entity.status,
            "requested_symbols": entity.requested_symbols or [],
            "imported_symbols": entity.imported_symbols or [],
            "records_inserted": entity.records_written,
            "records_received": entity.records_received,
            "attempts": entity.attempts,
            "max_attempts": entity.max_attempts,
            "errors": entity.errors or [],
            "notes": entity.notes,
            "created_at": _iso(entity.created_at),
            "updated_at": _iso(entity.updated_at),
            "started_at": _iso(entity.started_at),
            "finished_at": _iso(entity.finished_at),
        }
