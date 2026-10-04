from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from uuid import uuid4
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stock_ai.backtesting import BacktestConfig, ThresholdBacktester, _forecast_delta_pct
from stock_ai.contracts import dataset_version, normalize_bars
from stock_ai.models import StatisticalForecaster
from stock_ai.strategy import MonitorSignalBuilder
from portfolio_risk import PortfolioRiskService
from trading.store import TradingStore
from database.models import Base, Portfolio, Position, Recommendation, PaperOrder
from database.trading_store import SqlAlchemyTradingStore
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_quant_foundation import make_bars


class ResearchIntegrityTests(unittest.TestCase):
    def test_empty_database_upgrades_through_all_frozen_migrations(self):
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import create_engine, inspect
        with TemporaryDirectory() as folder:
            url = f"sqlite+pysqlite:///{Path(folder) / 'migrations.db'}"
            config = Config()
            config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
            config.set_main_option("sqlalchemy.url", url)
            with patch.dict("os.environ", {"DATABASE_URL": url}):
                command.upgrade(config, "head")
                command.upgrade(config, "head")
            engine = create_engine(url)
            inspector = inspect(engine)
            for table in Base.metadata.sorted_tables:
                self.assertEqual(set(table.c.keys()), {col["name"] for col in inspector.get_columns(table.name)})
            engine.dispose()

    def test_forward_price_output_does_not_reuse_holdout_predictions(self):
        from stock_ai.pipeline import StockAiPipeline, PredictionRequest
        class Market:
            def fetch_daily_bars(self, symbol, range_value):
                return make_bars(300, .002 if symbol == "TEST" else .001)
        with patch.dict("os.environ", {"MODEL_REGISTRY_DIR": ""}):
            result = StockAiPipeline(market_data=Market()).predict(PredictionRequest("TEST", 45, 5))
        self.assertEqual(result["forecast_mode"], "historical-holdout")
        self.assertNotEqual(result["predictions"], result["future_forecast"]["predictions"])
        self.assertEqual(result["future_forecast"]["as_of"], make_bars(300)[-1]["date"])
        self.assertTrue(result["quant_forecast"]["data_stale"])

    def test_ingestion_claim_is_atomic_between_workers(self):
        from market_data.store import MarketDataStore
        from database.market_store import SqlAlchemyMarketDataStore
        for sql in (False, True):
            with TemporaryDirectory() as folder:
                path = Path(folder) / "market.db"
                store = SqlAlchemyMarketDataStore(f"sqlite+pysqlite:///{path}") if sql else MarketDataStore(path)
                if sql:
                    Base.metadata.create_all(store.engine)
                else:
                    store.init_schema()
                job = store.create_import_batch(["TEST"], source="test")
                store.update_import_batch(job["id"], status="queued")
                with ThreadPoolExecutor(max_workers=2) as pool:
                    claimed = list(pool.map(lambda _: store.claim_import_batch(job["id"]), range(2)))
                self.assertEqual(sorted(claimed), [False, True])
                self.assertEqual(store.get_import_batch(job["id"])["attempts"], 1)
                if sql:
                    store.engine.dispose()

    def test_monitor_and_backtest_use_the_same_future_information(self):
        bars = make_bars(100)
        signal = MonitorSignalBuilder().build("TEST", bars)
        delta = _forecast_delta_pct(StatisticalForecaster(), [bar["close"] for bar in bars], 5)
        self.assertAlmostEqual(signal["forecast"]["delta_pct"], delta, places=4)
        class Spy:
            def forecast_series(self, values, window, steps):
                self.seen = values, window
                return [values[-1]] * steps
        spy = Spy()
        _forecast_delta_pct(spy, [1., 2., 3.], 2, 2)
        self.assertEqual(spy.seen, ([1., 2., 3.], 2))

    def test_content_hash_covers_prices_volume_benchmark_and_is_order_independent(self):
        bars = make_bars(80)
        benchmark = {bar["date"]: bar["close"] for bar in bars}
        original = dataset_version(bars, benchmark)
        self.assertEqual(original, dataset_version(list(reversed(bars)), dict(reversed(list(benchmark.items())))))
        for field in ("close", "adj_close", "high", "volume"):
            changed = deepcopy(bars)
            changed[30][field] *= 1.01
            self.assertNotEqual(original, dataset_version(changed, benchmark))
        changed_benchmark = dict(benchmark)
        changed_benchmark[bars[30]["date"]] *= 1.01
        self.assertNotEqual(original, dataset_version(bars, changed_benchmark))

    def test_bad_data_is_rejected_and_equity_dates_are_unique(self):
        bars = make_bars(80)
        with self.assertRaises(ValueError):
            normalize_bars(bars + [bars[0]])
        broken = deepcopy(bars)
        broken[3]["close"] = float("nan")
        with self.assertRaises(ValueError):
            ThresholdBacktester().run("TEST", broken)
        result = ThresholdBacktester().run("TEST", bars)
        self.assertEqual(result["equity_curve"][0]["equity"], 10000)
        dates = [row["date"] for row in result["equity_curve"]]
        self.assertEqual(len(dates), len(set(dates)))
        with self.assertRaises(ValueError):
            ThresholdBacktester().run("TEST", bars, BacktestConfig(initial_cash=float("nan")))

    def test_risk_uses_adjusted_prices_and_selected_account(self):
        class Market:
            def list_daily_bars(self, symbol, limit):
                return [{**bar, "trade_date": bar["date"]} for bar in make_bars(80, split_at=40)]
        class Trading:
            def get_portfolio(self, account):
                return {"equity": 10000, "positions": [{"symbol": s, "market_value": 2000} for s in ("A", "B")]}
            def get_performance(self, account):
                self.account = account
                return {"points": [{"portfolio_value": p} for p in (100, 110, 99)]}
        store = Trading()
        result = PortfolioRiskService(Market(), store).analyze(portfolio_id="secondary")
        self.assertEqual(store.account, "secondary")
        self.assertLess(result["portfolio"]["annualized_vol_pct"], .01)
        self.assertEqual(result["portfolio"]["max_drawdown_pct"], -10)


class OrderSafetyTests(unittest.TestCase):
    sql = False

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "orders.db"
        if self.sql:
            self.store = SqlAlchemyTradingStore(f"sqlite+pysqlite:///{self.path}")
            Base.metadata.create_all(self.store.engine)
            now = datetime.now(timezone.utc)
            with self.store.sessions.begin() as session:
                session.add(Portfolio(id="primary", name="Test", mode="paper", cash=20000, benchmark_symbol="SPY", created_at=now, updated_at=now))
                session.add(Position(portfolio_id="primary", symbol="NVDA", name="NVDA", quantity=10, average_cost=100, last_price=100, updated_at=now))
                session.add(Recommendation(symbol="NVDA", name="NVDA", score=80, stance="positive", horizon="5", latest_price=100, projected_return_pct=1, components_json="{}", thesis="test", risks_json="[]", source="test", generated_at=now, updated_at=now))
        else:
            self.store = TradingStore(self.path)
            self.store.init_schema()

    def tearDown(self):
        if self.sql:
            self.store.engine.dispose()
        self.temp.cleanup()

    def reopen_store(self):
        return SqlAlchemyTradingStore(f"sqlite+pysqlite:///{self.path}") if self.sql else TradingStore(self.path)

    def payload(self, side="buy", quantity=1):
        return {"symbol": "NVDA", "side": side, "quantity": quantity, "order_type": "market"}

    def test_reservations_prevent_oversized_combined_position_and_cancel_releases_them(self):
        portfolio = self.store.get_portfolio()
        position = next(p for p in portfolio["positions"] if p["symbol"] == "NVDA")
        room = portfolio["equity"] * .25 - position["market_value"]
        payload = self.payload(quantity=room * .7 / position["last_price"])
        first = self.store.create_order(payload, "first")
        second = self.store.create_order(payload, "second")
        self.assertEqual(first["status"], "awaiting_confirmation")
        self.assertEqual(second["status"], "risk_rejected")
        self.store.cancel_order(first["id"])
        self.assertEqual(self.store.cancel_order(first["id"])["status"], "cancelled")
        self.assertEqual(self.store.create_order(payload, "third")["status"], "awaiting_confirmation")

    def test_confirm_rechecks_legacy_drafts_without_reservations(self):
        portfolio = self.store.get_portfolio()
        position = next(p for p in portfolio["positions"] if p["symbol"] == "NVDA")
        amount = (portfolio["equity"] * .25 - position["market_value"]) * .7 / position["last_price"]
        first = self.store.create_order(self.payload(quantity=amount), "one")
        second = self.store.create_order(self.payload(quantity=amount), "two")
        # Simulate two awaiting drafts persisted by the previous application version.
        if self.sql:
            with self.store.sessions.begin() as session:
                session.get(PaperOrder, second["id"]).status = "awaiting_confirmation"
        else:
            with closing(self.store._connect()) as conn:
                conn.execute("UPDATE paper_orders SET status='awaiting_confirmation' WHERE id=?", (second["id"],))
                conn.commit()
        before = self.store.get_portfolio()["cash"]
        with self.assertRaisesRegex(ValueError, "25%"):
            self.store.confirm_order(first["id"])
        self.assertEqual(before, self.store.get_portfolio()["cash"])

    def test_repeat_confirmation_and_concurrent_retries_fill_once(self):
        draft = self.store.create_order(self.payload(), "retry")
        before = self.store.get_portfolio()["cash"]
        def confirm(_):
            other = self.reopen_store()
            try:
                return other.confirm_order(draft["id"])
            finally:
                if self.sql:
                    other.engine.dispose()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(confirm, range(2)))
        self.assertEqual([r["status"] for r in results], ["paper_filled"] * 2)
        self.assertAlmostEqual(before - self.store.get_portfolio()["cash"], results[0]["filled_price"], places=2)

    def test_halt_blocks_confirmation_and_survives_store_restart(self):
        draft = self.store.create_order(self.payload(), "halt")
        self.store.set_trading_halted(True)
        self.assertTrue(self.store.get_trading_control()["halted"])
        with self.assertRaisesRegex(ValueError, "halted"):
            self.store.confirm_order(draft["id"])
        self.assertEqual(self.store.create_order(self.payload(), "halt-new")["status"], "risk_rejected")
        self.store.set_trading_halted(False)
        self.assertEqual(self.store.confirm_order(draft["id"])["status"], "paper_filled")

    def test_limit_cannot_fill_at_an_unreached_price(self):
        payload = {**self.payload(), "order_type": "limit", "limit_price": .01}
        draft = self.store.create_order(payload, "limit")
        with self.assertRaisesRegex(ValueError, "limit price"):
            self.store.confirm_order(draft["id"])

    def test_reused_id_with_different_payload_and_nonfinite_numbers_rejected(self):
        self.store.create_order(self.payload(), "same")
        with self.assertRaisesRegex(ValueError, "different order"):
            self.store.create_order(self.payload(quantity=2), "same")
        for value in (float("nan"), float("inf"), -1):
            with self.assertRaises(ValueError):
                self.store.create_order(self.payload(quantity=value))


class SqlAlchemyOrderSafetyTests(OrderSafetyTests):
    sql = True


@unittest.skipUnless(os.getenv("TEST_POSTGRES_URL"), "set TEST_POSTGRES_URL for isolated PostgreSQL integration tests")
class PostgresOrderSafetyTests(OrderSafetyTests):
    sql = True

    def setUp(self):
        from sqlalchemy.schema import CreateSchema
        self.schema = "quant_test_" + uuid4().hex
        self.store = SqlAlchemyTradingStore(os.environ["TEST_POSTGRES_URL"])
        with self.store.engine.begin() as conn:
            conn.execute(CreateSchema(self.schema))
        self.store.engine = self.store.engine.execution_options(schema_translate_map={None: self.schema})
        from database.session import session_factory
        self.store.sessions = session_factory(self.store.engine)
        Base.metadata.create_all(self.store.engine)
        now = datetime.now(timezone.utc)
        with self.store.sessions.begin() as session:
            session.add(Portfolio(id="primary", name="Test", mode="paper", cash=20000, benchmark_symbol="SPY", created_at=now, updated_at=now))
            session.flush()
            session.add(Position(portfolio_id="primary", symbol="NVDA", name="NVDA", quantity=10, average_cost=100, last_price=100, updated_at=now))
            session.add(Recommendation(symbol="NVDA", name="NVDA", score=80, stance="positive", horizon="5", latest_price=100, projected_return_pct=1, components_json="{}", thesis="test", risks_json="[]", source="test", generated_at=now, updated_at=now))

    def reopen_store(self):
        from database.session import session_factory
        store = SqlAlchemyTradingStore(os.environ["TEST_POSTGRES_URL"])
        store.engine = store.engine.execution_options(schema_translate_map={None: self.schema})
        store.sessions = session_factory(store.engine)
        return store

    def tearDown(self):
        from sqlalchemy.schema import DropSchema
        # Only the random schema created by this test is removed; application tables are untouched.
        assert self.schema.startswith("quant_test_") and len(self.schema) == 43
        with self.store.engine.begin() as conn:
            conn.execute(DropSchema(self.schema, cascade=True))
        self.store.engine.dispose()


class RegistryTests(unittest.TestCase):
    @unittest.skipUnless(__import__("importlib.util").util.find_spec("sklearn"), "optional sklearn not installed")
    def test_artifact_roundtrip_never_refits_and_rejects_corruption_or_failed_gate(self):
        from stock_ai.research import train_run, activate_run, registered_prediction
        from stock_ai.excess_returns import MultiHorizonExcessReturnForecaster
        stock, benchmark = make_bars(300, .002), make_bars(300, .001)
        # Real fitting/serialization, with a deterministic validation fixture to exercise activation.
        validation = {"eligible": True, "metrics": [], "gate": "test fixture"}
        with TemporaryDirectory() as folder, patch("stock_ai.research.evaluate_excess", return_value=validation):
            root = Path(folder)
            manifest = train_run(root, "TEST", stock, benchmark)
            activate_run(root, manifest["run_id"])
            with patch("stock_ai.research.date") as clock:
                from datetime import date
                clock.today.return_value = date(2025, 11, 1)
                clock.fromisoformat.side_effect = date.fromisoformat
                with patch("sklearn.ensemble.HistGradientBoostingRegressor.fit", side_effect=AssertionError("online fitting")):
                    result = registered_prediction(root, "TEST", stock, benchmark)
                self.assertFalse(result["fallback_used"])
                self.assertEqual(result["model_run_id"], manifest["run_id"])
                self.assertFalse(result["production_eligible"])
            artifact = root / manifest["run_id"] / "model.pkl"
            artifact.write_bytes(artifact.read_bytes() + b"corrupted")
            with self.assertRaisesRegex(ValueError, "checksum"):
                activate_run(root, manifest["run_id"])
            manifest["validation"]["eligible"] = False
            (root / manifest["run_id"] / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "gate"):
                activate_run(root, manifest["run_id"])

    def test_walk_forward_never_observes_future_labels(self):
        from stock_ai.research import evaluate_excess
        from stock_ai.excess_returns import MultiHorizonExcessReturnForecaster
        cutoffs = []
        class FakeForecaster:
            def __init__(self, allow_training=False):
                self.training = allow_training
            def predict(self, stock, benchmark):
                cutoff = stock[-1]["date"]
                assert all(row["date"] <= cutoff for row in benchmark)
                if self.training:
                    cutoffs.append(cutoff)
                return {"fallback_used": False, "forecasts": [
                    {"horizon_days": h, "excess_return_pct": 0.} for h in (5, 20)
                ]}
        with patch("stock_ai.research.MultiHorizonExcessReturnForecaster", FakeForecaster):
            report = evaluate_excess(make_bars(500, .002), make_bars(500, .001))
        self.assertEqual(len(cutoffs), 12)
        self.assertFalse(report["eligible"])
        for metric in report["metrics"]:
            for row in metric["observations"]:
                self.assertGreater(row["label_end"], row["as_of"])

    def test_archive_scoring_excludes_retrospective_and_duplicate_requests(self):
        from stock_ai.research import score_archived_predictions, write_json
        stock, benchmark = make_bars(100, .002), make_bars(100, .001)
        with TemporaryDirectory() as folder:
            root = Path(folder)
            item = {"symbol": "TEST", "recorded_at": stock[70]["date"] + "T22:00:00+00:00",
                    "prediction": {"data_cutoff": stock[70]["date"], "model_id": "test",
                                   "forecasts": [{"horizon_days": 5, "excess_return_pct": 1.}]}}
            write_json(root / "predictions" / "one.json", item)
            write_json(root / "predictions" / "duplicate.json", item)
            late = deepcopy(item)
            late["recorded_at"] = stock[90]["date"] + "T22:00:00+00:00"
            write_json(root / "predictions" / "late.json", late)
            report = score_archived_predictions(root, "TEST", stock, benchmark)
            self.assertEqual(report["evaluated"], 1)
            self.assertEqual(report["retrospective_excluded"], 1)


class ApiAccessTests(unittest.TestCase):
    def test_remote_access_requires_token_and_token_is_checked(self):
        from app import app
        client = app.test_client()
        with patch.dict("os.environ", {"API_ACCESS_TOKEN": ""}):
            self.assertEqual(client.get("/trading/control", environ_base={"REMOTE_ADDR": "192.0.2.1"}).status_code, 403)
            self.assertEqual(client.post("/trading/orders/unknown/confirm", headers={"Origin": "https://untrusted.example"}).status_code, 403)
        with patch.dict("os.environ", {"API_ACCESS_TOKEN": "test-token"}):
            self.assertEqual(client.get("/trading/control").status_code, 401)
            self.assertEqual(client.get("/trading/control", headers={"Authorization": "Bearer test-token"}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
