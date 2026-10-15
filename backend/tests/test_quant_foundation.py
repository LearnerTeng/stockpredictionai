from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database.market_store import SqlAlchemyMarketDataStore  # noqa: E402
from database.models import Base, Portfolio, Position, Recommendation  # noqa: E402
from database.trading_store import SqlAlchemyTradingStore  # noqa: E402
from market_data.ingestion import IngestionService  # noqa: E402
from market_data.store import MarketDataStore  # noqa: E402
from stock_ai.contracts import QuantObjective, adjusted_bars  # noqa: E402
from stock_ai.excess_returns import MultiHorizonExcessReturnForecaster  # noqa: E402


def make_bars(count: int = 80, daily_return: float = 0.001, *, split_at: int | None = None) -> list[dict]:
    start = date(2025, 1, 1)
    adjusted = 100.0
    bars: list[dict] = []
    for index in range(count):
        adjusted *= 1 + daily_return
        raw = adjusted / 2 if split_at is not None and index < split_at else adjusted
        bars.append(
            {
                "date": (start + timedelta(days=index)).isoformat(),
                "open": raw,
                "high": raw * 1.01,
                "low": raw * 0.99,
                "close": raw,
                "adj_close": adjusted,
                "volume": 1_000_000 + index,
            }
        )
    return bars


class QuantContractTests(unittest.TestCase):
    def test_default_objective_is_direct_5_and_20_day_spy_excess_return(self) -> None:
        objective = QuantObjective().to_dict()
        self.assertEqual(objective["horizons"], [5, 20])
        self.assertEqual(objective["benchmark"], "SPY")
        self.assertEqual(objective["price_field"], "adj_close")
        self.assertEqual(objective["target"], "excess_return")

    def test_adjusted_bars_remove_raw_split_jump(self) -> None:
        bars = make_bars(split_at=40)
        adjusted = adjusted_bars(bars)
        returns = [adjusted[index]["close"] / adjusted[index - 1]["close"] - 1 for index in range(1, len(adjusted))]
        self.assertLess(max(abs(value) for value in returns), 0.01)

    def test_online_excess_forecast_explicitly_uses_fallback_without_registered_model(self) -> None:
        stock = make_bars(260, 0.002)
        benchmark = make_bars(260, 0.001)
        result = MultiHorizonExcessReturnForecaster().predict(stock, benchmark)

        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["fallback_reason"], "no-registered-model")
        self.assertEqual([item["horizon_days"] for item in result["forecasts"]], [5, 20])
        self.assertGreater(result["forecasts"][0]["excess_return_pct"], 0)
        self.assertTrue(result["dataset_version"].startswith("dataset-"))


class FakeProvider:
    def __init__(self) -> None:
        self.calls: dict[str, int] = {}

    def fetch_daily_bars(self, symbol: str, range_value: str) -> list[dict]:
        self.calls[symbol] = self.calls.get(symbol, 0) + 1
        if symbol == "AAPL" and self.calls[symbol] == 1:
            raise RuntimeError("temporary upstream failure")
        return make_bars(45)

    def fetch_corporate_actions(self, symbol: str, range_value: str) -> list[dict]:
        return [{"date": "2025-02-01", "type": "dividend", "value": 0.25}]


class IngestionTests(unittest.TestCase):
    def test_queue_adds_spy_retries_and_persists_audit(self) -> None:
        with TemporaryDirectory() as directory:
            store = MarketDataStore(Path(directory) / "market.db")
            store.init_schema()
            provider = FakeProvider()
            service = IngestionService(store, provider, sleeper=lambda _seconds: None)
            job = service.enqueue(["AAPL"], range_value="10y", max_attempts=2)
            completed = service._futures[job["id"]].result(timeout=10)

            self.assertEqual(completed["status"], "completed")
            self.assertEqual(completed["requested_symbols"], ["AAPL", "SPY"])
            self.assertEqual(provider.calls["AAPL"], 2)
            self.assertEqual(completed["errors"], [])
            self.assertGreaterEqual(completed["records_inserted"], 90)
            self.assertEqual(len(store.list_daily_bars("AAPL", 5000)), 45)
            service.executor.shutdown(wait=True)

    def test_sqlalchemy_repository_supports_sqlite_for_contract_tests(self) -> None:
        with TemporaryDirectory() as directory:
            database_url = f"sqlite+pysqlite:///{Path(directory) / 'unified.db'}"
            store = SqlAlchemyMarketDataStore(database_url)
            Base.metadata.create_all(store.engine)
            store.upsert_symbols([{"symbol": "AAPL", "market": "US", "status": "active"}])
            store.ingest_daily_bars("AAPL", make_bars(5), source="test")

            self.assertEqual(store.universe_summary()["symbols_count"], 1)
            self.assertEqual(len(store.list_daily_bars("AAPL", 10)), 5)
            store.engine.dispose()

    def test_sqlalchemy_trading_repository_preserves_two_step_order_contract(self) -> None:
        from datetime import datetime, timezone

        with TemporaryDirectory() as directory:
            database_url = f"sqlite+pysqlite:///{Path(directory) / 'trading.db'}"
            store = SqlAlchemyTradingStore(database_url)
            Base.metadata.create_all(store.engine)
            now = datetime.now(timezone.utc)
            with store.sessions.begin() as session:
                session.add(Portfolio(id="primary", name="Test", mode="paper", cash=20_000, benchmark_symbol="SPY", created_at=now, updated_at=now))
                session.add(Position(portfolio_id="primary", symbol="NVDA", name="NVIDIA", quantity=1, average_cost=100, last_price=120, updated_at=now))
                session.add(Portfolio(id="nisa", name="NISA", mode="read_only", currency="JPY", account_type="nisa", cash=0, benchmark_symbol="", created_at=now, updated_at=now))
                session.add(Position(portfolio_id="nisa", symbol="FUND", name="Fund", currency="JPY", account_bucket="growth", quantity=20_000, average_cost=10_000, last_price=12_000, price_scale=10_000, reported_market_value=24_001, reported_cost_basis=20_000, source="test", updated_at=now))
                session.add(Recommendation(symbol="NVDA", name="NVIDIA", score=80, stance="positive", horizon="5 trading days", latest_price=120, projected_return_pct=2, components_json="{}", thesis="test", risks_json="[]", source="test", generated_at=now, updated_at=now))

            draft = store.create_order({"symbol": "NVDA", "side": "buy", "quantity": 1, "order_type": "market"}, "sqlalchemy-order")
            filled = store.confirm_order(draft["id"])

            self.assertEqual(draft["status"], "awaiting_confirmation")
            self.assertEqual(filled["status"], "paper_filled")
            self.assertEqual(store.get_portfolio()["positions"][0]["quantity"], 2)
            nisa = store.get_portfolio("nisa")
            self.assertEqual(nisa["currency"], "JPY")
            self.assertEqual(nisa["market_value"], 24_001)
            self.assertEqual(nisa["positions"][0]["price_scale"], 10_000)
            self.assertEqual({item["id"] for item in store.list_portfolios()}, {"primary", "nisa"})
            store.engine.dispose()


if __name__ == "__main__":
    unittest.main()
