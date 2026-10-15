from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock
from time import sleep
from typing import Any, Callable

from .store import normalize_symbol


TERMINAL_STATUSES = {"completed", "partial", "failed"}


class IngestionService:
    """Database-audited ingestion queue with an in-process local worker.

    Queued rows remain recoverable by the standalone worker after a process
    restart. The in-process executor keeps local development ergonomic.
    """

    def __init__(
        self,
        store: Any,
        provider: Any,
        *,
        on_symbol: Callable[[str, list[dict[str, Any]]], None] | None = None,
        max_workers: int = 1,
        sleeper: Callable[[float], None] = sleep,
    ):
        self.store = store
        self.provider = provider
        self.on_symbol = on_symbol
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="market-ingestion")
        self.sleeper = sleeper
        self._lock = Lock()
        self._futures: dict[str, Future[dict[str, Any]]] = {}

    def enqueue(
        self,
        symbols: list[str],
        *,
        range_value: str = "10y",
        source: str = "yahoo",
        include_benchmark: bool = True,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        normalized = list(dict.fromkeys(normalize_symbol(symbol) for symbol in symbols))
        if include_benchmark and "SPY" not in normalized:
            normalized.append("SPY")
        if not normalized:
            raise ValueError("symbols must contain at least one symbol")
        if max_attempts < 1 or max_attempts > 10:
            raise ValueError("max_attempts must be between 1 and 10")
        with self._lock:
            for active_id, future in self._futures.items():
                if future.done():
                    continue
                active = self.store.get_import_batch(active_id)
                overlap = set(normalized) & set(active.get("requested_symbols") or [])
                if overlap:
                    raise ValueError(f"ingestion already running for: {', '.join(sorted(overlap))}")
        batch = self.store.create_import_batch(normalized, source=f"{source}-{range_value}", notes="Queued ingestion")
        batch = self.store.update_import_batch(
            batch["id"],
            status="queued",
            request_payload={"range": range_value, "source": source, "include_benchmark": include_benchmark},
            max_attempts=max_attempts,
            errors=[],
        )
        with self._lock:
            self._futures[batch["id"]] = self.executor.submit(self.run, batch["id"])
        return batch

    def run(self, batch_id: str) -> dict[str, Any]:
        batch = self.store.get_import_batch(batch_id)
        if batch["status"] in TERMINAL_STATUSES:
            return batch
        if not self.store.claim_import_batch(batch_id):
            return self.store.get_import_batch(batch_id)
        payload = batch.get("request_payload") or {}
        range_value = str(payload.get("range") or "10y")
        source = str(payload.get("source") or "yahoo")
        max_attempts = int(batch.get("max_attempts") or 3)

        imported: list[str] = []
        errors: list[dict[str, Any]] = []
        records_written = 0
        for symbol in batch["requested_symbols"]:
            symbol_error: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    bars = self.provider.fetch_daily_bars(symbol, range_value)
                    result = self.store.ingest_daily_bars(symbol, bars, source=source, batch_id=batch_id)
                    actions = (
                        self.provider.fetch_corporate_actions(symbol, range_value)
                        if hasattr(self.provider, "fetch_corporate_actions")
                        else []
                    )
                    if actions and hasattr(self.store, "ingest_corporate_actions"):
                        self.store.ingest_corporate_actions(symbol, actions, source=source)
                    if self.on_symbol is not None:
                        self.on_symbol(symbol, bars)
                    imported.append(symbol)
                    records_written += int(result.get("rows_received") or len(bars))
                    symbol_error = None
                    break
                except Exception as err:  # noqa: BLE001 - persisted per-symbol failure
                    symbol_error = err
                    if attempt < max_attempts:
                        self.sleeper(min(2 ** (attempt - 1), 8))
            if symbol_error is not None:
                errors.append({"symbol": symbol, "error": str(symbol_error), "attempts": max_attempts})

        status = "completed" if not errors else "partial" if imported else "failed"
        finished = datetime.now(timezone.utc).isoformat()
        return self.store.update_import_batch(
            batch_id,
            status=status,
            imported_symbols=imported,
            records_inserted=records_written,
            errors=errors,
            finished_at=finished,
        )

    def recover_pending(self, limit: int = 10) -> list[str]:
        submitted: list[str] = []
        for batch in self.store.list_pending_import_batches(limit):
            with self._lock:
                future = self._futures.get(batch["id"])
                if future is not None and not future.done():
                    continue
                self._futures[batch["id"]] = self.executor.submit(self.run, batch["id"])
            submitted.append(batch["id"])
        return submitted
