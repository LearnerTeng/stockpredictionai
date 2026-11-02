from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import json
import os
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database.models import Base, BarRevision, Portfolio, Position, Recommendation
from database.market_store import SqlAlchemyMarketDataStore
from database.trading_store import SqlAlchemyTradingStore
from market_data.calendar import next_session, session_close
from market_data.point_in_time import import_security_master, universe_as_of
from stock_ai.portfolio_backtest import run_portfolio_backtest, PortfolioBacktestConfig
from stock_ai.forward_monitor import summarize
from trading.ledger import reconcile
from sqlalchemy import select, func


class PointInTimeTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.store = SqlAlchemyMarketDataStore(f"sqlite:///{Path(self.folder.name)/'test.db'}")
        Base.metadata.create_all(self.store.engine)

    def tearDown(self):
        self.store.engine.dispose()
        self.folder.cleanup()

    def test_backfill_is_not_visible_in_past_and_revisions_replay(self):
        first = datetime(2026, 9, 8, 22, tzinfo=timezone.utc)
        bar = {"date": "2026-09-08", "close": 100, "volume": 1000}
        with patch("database.market_store._now", return_value=first):
            self.store.ingest_daily_bars("TEST", [bar])
            self.store.ingest_daily_bars("TEST", [bar])
        with self.store.sessions() as session:
            row = session.scalar(select(BarRevision))
            sid = row.security_id
            self.assertEqual(session.scalar(select(func.count()).select_from(BarRevision)), 1)
        self.assertEqual(self.store.list_bars_as_of(sid, "2026-09-08T21:00:00Z", source="manual"), [])
        later = first + timedelta(days=1)
        with patch("database.market_store._now", return_value=later):
            self.store.ingest_daily_bars("TEST", [{**bar, "close": 101}])
        self.assertEqual(self.store.list_bars_as_of(sid, first, source="manual")[0]["close"], 100)
        self.assertEqual(self.store.list_bars_as_of(sid, later, source="manual")[0]["close"], 101)
        self.assertEqual(self.store.list_bars_as_of(sid, later, source="manual", known_at=first)[0]["close"], 100)

    def test_master_membership_and_holiday_quarantine(self):
        payload = {"securities": [{"id": "security-1", "market": "US", "currency": "USD"}],
            "aliases": [{"security_id": "security-1", "symbol": "TEST", "valid_from": "2026-01-01", "available_at": "2025-12-01T00:00:00Z"}],
            "memberships": [{"security_id": "security-1", "universe": "TEST", "valid_from": "2026-01-01",
                             "valid_to": "2026-09-09", "available_at": "2025-12-01T00:00:00Z"}]}
        import_security_master(self.store.sessions, payload)
        import_security_master(self.store.sessions, payload)
        self.assertEqual(universe_as_of(self.store.sessions, "TEST", "2026-09-08T22:00:00Z"), ["security-1"])
        self.assertEqual(universe_as_of(self.store.sessions, "TEST", "2026-09-09T22:00:00Z"), [])
        self.store.ingest_daily_bars("TEST", [{"date": "2026-09-07", "close": 100}])
        self.assertEqual(self.store.list_bars_as_of("security-1", "2027-01-01T00:00:00Z", source="manual"), [])

    def test_quarantined_observation_can_be_replaced_by_valid_close(self):
        bar = {"date": "2026-09-08", "close": 100}
        with patch("database.market_store._now", return_value=datetime(2026, 9, 8, 18, tzinfo=timezone.utc)):
            self.store.ingest_daily_bars("TEST", [bar])
        with patch("database.market_store._now", return_value=datetime(2026, 9, 8, 22, tzinfo=timezone.utc)):
            self.store.ingest_daily_bars("TEST", [bar])
        with self.store.sessions() as session:
            rows = session.scalars(select(BarRevision).order_by(BarRevision.revision)).all()
            self.assertEqual([r.quality_status for r in rows], ["quarantined", "accepted"])
            sid = rows[0].security_id
        self.assertEqual(len(self.store.list_bars_as_of(sid, "2026-09-08T23:00:00Z", source="manual")), 1)


def portfolio_fixture():
    days = ["2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-08", "2026-09-09"]
    bars = [{"date": day, "open": 100+i, "close": 100+i, "adj_close": 100+i,
             "volume": 10000, "available_at": session_close(date.fromisoformat(day)).isoformat()} for i, day in enumerate(days)]
    return {"benchmark": bars, "assets": {"a": {"bars": bars, "market": "US", "currency": "USD", "sector": "tech"}},
            "memberships": [{"security_id": "a", "valid_from": days[0], "available_at": days[0]+"T00:00:00Z"}]}


class PortfolioReplayTests(unittest.TestCase):
    def config(self, **changes):
        return PortfolioBacktestConfig(lookback=2, rebalance_sessions=1, **changes)

    def test_next_session_and_ledger_costs(self):
        data = portfolio_fixture()
        result = run_portfolio_backtest(data, self.config())
        self.assertEqual(result["fills"][0]["signal_date"], "2026-09-02")
        self.assertEqual(result["fills"][0]["date"], "2026-09-03")
        self.assertTrue(all(p["cash"] >= -1e-8 for p in result["equity_curve"]))
        self.assertTrue(all(f["quantity"] <= 100 for f in result["fills"]))
        free = run_portfolio_backtest(data, self.config(commission_bps=0, slippage_bps=0, impact_bps=0))
        self.assertGreater(free["equity_curve"][-1]["equity"], result["equity_curve"][-1]["equity"])
        changed = deepcopy(data)
        changed["assets"]["a"]["bars"][-1]["close"] = 120
        later = run_portfolio_backtest(changed, self.config())
        self.assertEqual(result["fills"][:2], later["fills"][:2])

    def test_missing_held_bar_fails_and_late_information_is_excluded(self):
        data = portfolio_fixture()
        data["assets"]["a"]["bars"] = [b for b in data["assets"]["a"]["bars"] if b["date"] != "2026-09-04"]
        with self.assertRaisesRegex(ValueError, "missing valuation"):
            run_portfolio_backtest(data, self.config())
        data = portfolio_fixture()
        for bar in data["assets"]["a"]["bars"]:
            bar["available_at"] = "2027-01-01T00:00:00Z"
        self.assertEqual(run_portfolio_backtest(data, self.config())["fills"], [])

    def test_split_dividend_and_delisting(self):
        data = portfolio_fixture()
        for bar in data["assets"]["a"]["bars"]:
            if bar["date"] >= "2026-09-04":
                bar["open"] /= 2
                bar["close"] /= 2
        data["actions"] = [
            {"date": "2026-09-04", "security_id": "a", "type": "split", "value": 2},
            {"date": "2026-09-08", "security_id": "a", "type": "dividend", "value": 1},
            {"date": "2026-09-09", "security_id": "a", "type": "delisting", "value": 53}]
        result = run_portfolio_backtest(data, self.config())
        self.assertGreater(result["equity_curve"][-1]["equity"], 99_000)
        self.assertEqual(result["equity_curve"][-1]["holdings"], {})
        self.assertEqual(len(result["cash_events"]), 2)

    def test_invalid_configuration_and_unknown_calendar_date(self):
        with self.assertRaises(ValueError):
            run_portfolio_backtest(portfolio_fixture(), self.config(max_weight=float("nan")))
        data = portfolio_fixture()
        data["benchmark"][1]["date"] = "2026-09-07"
        with self.assertRaises(ValueError):
            run_portfolio_backtest(data, self.config())

    def test_rejects_early_daily_bar_and_duplicate_actions(self):
        data = portfolio_fixture()
        data["assets"]["a"]["bars"][0]["available_at"] = "2026-08-31T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "before its session close"):
            run_portfolio_backtest(data, self.config())
        data = portfolio_fixture()
        action = {"date": "2026-09-04", "security_id": "a", "type": "dividend", "value": 1}
        data["actions"] = [action, action]
        with self.assertRaisesRegex(ValueError, "unique"):
            run_portfolio_backtest(data, self.config())


class ForwardTests(unittest.TestCase):
    def test_deactivation_requires_fresh_data_and_matching_active_model(self):
        from stock_ai.forward_monitor import run_monitor
        from unittest.mock import Mock
        fake_store = Mock()
        observations = [{"model": "model", "horizon_days": 5, "as_of": f"2026-08-{i:02}",
                         "label_end": f"2026-08-{i+5:02}", "actual_pct": 1.,
                         "predicted_pct": -2., "absolute_error_pct": 3.} for i in (1, 6, 11)]
        scored = {"observations": observations, "pending": 0, "retrospective_excluded": 0}
        with TemporaryDirectory() as folder, patch("stock_ai.registry.active_models", return_value={"TEST": "model"}), patch("stock_ai.registry.deactivate_model", return_value={"run_id": None}) as deactivate, patch("stock_ai.forward_monitor.registered_prediction", return_value={}), patch("stock_ai.forward_monitor.score_archived_predictions", return_value=scored):
            fake_store.list_daily_bars.return_value = [{"date": "2026-09-04", "close": 100}]
            now = datetime(2026, 9, 8, 22, tzinfo=timezone.utc)
            stale = run_monitor(Path(folder), fake_store, min_samples=3, disable_degraded=True, now=now)
            self.assertTrue(stale["results"][0]["data_stale"])
            deactivate.assert_not_called()
            fake_store.list_daily_bars.return_value = [{"date": "2026-09-08", "close": 100}]
            fresh = run_monitor(Path(folder), fake_store, min_samples=3, disable_degraded=True, now=now)
            self.assertEqual(fresh["results"][0]["action"], {"run_id": None})
            self.assertEqual(deactivate.call_args.args[1:3], ("TEST", "model"))

    def test_future_data_blocks_scoring_and_deactivation(self):
        from stock_ai.forward_monitor import run_monitor
        from unittest.mock import Mock
        fake_store = Mock()
        fake_store.list_daily_bars.return_value = [{"date": "2026-09-09", "close": 100}]
        with TemporaryDirectory() as folder, patch("stock_ai.registry.active_models", return_value={"TEST": "model"}), patch("stock_ai.registry.deactivate_model") as deactivate:
            report = run_monitor(Path(folder), fake_store, disable_degraded=True,
                                 now=datetime(2026, 9, 8, 22, tzinfo=timezone.utc))
            self.assertEqual(report["status"], "error")
            deactivate.assert_not_called()

    def test_overlapping_outcomes_not_counted_and_degradation(self):
        rows = [{"model": "m", "horizon_days": 5, "as_of": f"2026-09-{i:02}",
                 "label_end": f"2026-09-{i+5:02}", "actual_pct": 1., "predicted_pct": -2.,
                 "absolute_error_pct": 3.} for i in range(1, 20)]
        report = summarize(rows, min_samples=3)[0]
        self.assertEqual(report["samples"], 4)
        self.assertEqual(report["status"], "degraded")
        self.assertEqual(summarize(rows, min_samples=20)[0]["status"], "insufficient-samples")

    def test_exchange_holidays_and_early_close(self):
        self.assertEqual(next_session(date(2026, 9, 4)), date(2026, 9, 8))
        self.assertEqual(session_close(date(2026, 11, 27)).hour, 18)
        self.assertEqual(next_session(date(2026, 1, 1), "JP"), date(2026, 1, 5))

    def test_database_registry_is_single_authority(self):
        from stock_ai.registry import register_manifest, active_models, select_model, deactivate_model
        with TemporaryDirectory() as folder:
            url = f"sqlite:///{Path(folder)/'registry.db'}"
            store = SqlAlchemyMarketDataStore(url)
            Base.metadata.create_all(store.engine)
            with patch.dict(os.environ, {"DATABASE_URL": url}):
                root = Path(folder)
                manifest = {"run_id": "a"*32, "symbol": "TEST", "dataset_version": "dataset-"+"b"*64,
                    "trained_until": "2026-09-08", "features": [], "objective": {"benchmark": "SPY", "horizons": [5, 20]},
                    "validation": {"eligible": True}}
                register_manifest(manifest, root)
                register_manifest(manifest, root)  # repeated import is safe
                with self.assertRaisesRegex(ValueError, "immutable"):
                    register_manifest({**manifest, "features": ["changed"]}, root)
                select_model(root, "TEST", "a"*32, "test")
                self.assertEqual(active_models(root), {"TEST": "a"*32})
                self.assertFalse((root / "active.json").exists())
                with self.assertRaises(ValueError):
                    deactivate_model(root, "TEST", "c"*32, "test")
                deactivate_model(root, "TEST", "a"*32, "test")
                self.assertEqual(active_models(root), {})
            store.engine.dispose()


class LedgerTests(unittest.TestCase):
    def test_transactional_fill_idempotency_and_statement_diff(self):
        from database.models import Fill, ExecutionEvent
        with TemporaryDirectory() as folder:
            store = SqlAlchemyTradingStore(f"sqlite:///{Path(folder)/'ledger.db'}")
            Base.metadata.create_all(store.engine)
            now = datetime.now(timezone.utc)
            with store.sessions.begin() as session:
                session.add(Portfolio(id="primary", name="Paper", mode="paper", currency="USD", cash=10000,
                    benchmark_symbol="SPY", created_at=now, updated_at=now))
                session.add(Recommendation(symbol="TEST", name="Test", score=70, stance="positive", horizon="5",
                    latest_price=100, projected_return_pct=1, components_json="{}", thesis="", risks_json="[]",
                    source="test", generated_at=now, updated_at=now))
            draft = store.create_order({"symbol": "TEST", "side": "buy", "quantity": 1}, "once")
            store.confirm_order(draft["id"])
            store.confirm_order(draft["id"])
            with store.sessions() as session:
                self.assertEqual(session.scalar(select(func.count()).select_from(Fill)), 1)
                self.assertEqual(session.scalar(select(func.count()).select_from(ExecutionEvent)), 2)
            self.assertEqual(reconcile(store.sessions)["status"], "matched")
            report = reconcile(store.sessions, statement={"cash": 9900, "currency": "USD", "positions": {"TEST": 2}})
            self.assertEqual(report["differences"][0]["field"], "position")
            store.engine.dispose()


if __name__ == "__main__":
    unittest.main()
