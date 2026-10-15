from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app import app  # noqa: E402
from trading.store import TradingStore  # noqa: E402


def make_bars(count: int = 80) -> list[dict]:
    from datetime import date, timedelta

    bars = []
    price = 100.0
    start = date(2026, 1, 1)
    for index in range(count):
        price += 0.4
        bars.append(
            {
                "date": (start + timedelta(days=index)).isoformat(),
                "close": round(price, 4),
                "open": round(price - 0.2, 4),
                "high": round(price + 0.5, 4),
                "low": round(price - 0.5, 4),
                "volume": 1_000_000 + index,
            }
        )
    return bars


class TradingStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.store = TradingStore(Path(self.temp_dir.name) / "trading-test.db")
        self.store.init_schema()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_seeded_dashboard_contract(self) -> None:
        dashboard = self.store.get_dashboard()
        self.assertEqual(dashboard["data_mode"], "demo")
        self.assertEqual(dashboard["portfolio"]["mode"], "paper")
        self.assertGreater(dashboard["portfolio"]["equity"], 0)
        self.assertGreaterEqual(len(dashboard["recommendations"]), 4)

    def test_order_requires_confirmation_then_updates_portfolio(self) -> None:
        before = self.store.get_portfolio()
        order = self.store.create_order(
            {"symbol": "NVDA", "side": "buy", "quantity": 1, "order_type": "market"},
            "confirm-flow",
        )
        self.assertEqual(order["status"], "awaiting_confirmation")
        self.assertTrue(order["risk_result"]["approved"])

        filled = self.store.confirm_order(order["id"])
        after = self.store.get_portfolio()
        self.assertEqual(filled["status"], "paper_filled")
        self.assertLess(after["cash"], before["cash"])
        nvda = next(position for position in after["positions"] if position["symbol"] == "NVDA")
        self.assertEqual(nvda["quantity"], 19)

    def test_risk_policy_rejects_oversized_order(self) -> None:
        order = self.store.create_order(
            {"symbol": "NVDA", "side": "buy", "quantity": 100, "order_type": "market"},
            "oversized-order",
        )
        self.assertEqual(order["status"], "risk_rejected")
        self.assertFalse(order["risk_result"]["approved"])

    def test_client_order_id_is_idempotent(self) -> None:
        payload = {"symbol": "MSFT", "side": "buy", "quantity": 1, "order_type": "market"}
        first = self.store.create_order(payload, "same-client-id")
        second = self.store.create_order(payload, "same-client-id")
        self.assertEqual(first["id"], second["id"])


class TradingApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.store = TradingStore(Path(self.temp_dir.name) / "api-test.db")
        self.store.init_schema()
        self.patch = patch("app.trading_store", self.store)
        self.patch.start()
        self.client = app.test_client()

    def tearDown(self) -> None:
        self.patch.stop()
        self.temp_dir.cleanup()

    def test_dashboard_and_recommendations(self) -> None:
        dashboard = self.client.get("/dashboard")
        recommendations = self.client.get("/recommendations")
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(recommendations.status_code, 200)
        self.assertEqual(dashboard.get_json()["portfolio"]["mode"], "paper")
        self.assertGreater(len(recommendations.get_json()["items"]), 0)

    def test_portfolio_list_and_selection_api(self) -> None:
        listed = self.client.get("/portfolios")
        selected = self.client.get("/portfolio?id=primary")

        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.get_json()["items"][0]["currency"], "USD")
        self.assertEqual(selected.status_code, 200)
        self.assertEqual(selected.get_json()["id"], "primary")

    def test_two_step_order_api(self) -> None:
        draft_response = self.client.post(
            "/trading/orders",
            json={"symbol": "NVDA", "side": "buy", "quantity": 1, "order_type": "market"},
            headers={"Idempotency-Key": "api-order"},
        )
        self.assertEqual(draft_response.status_code, 201)
        draft = draft_response.get_json()
        self.assertEqual(draft["status"], "awaiting_confirmation")

        confirm_response = self.client.post(f"/trading/orders/{draft['id']}/confirm")
        self.assertEqual(confirm_response.status_code, 200)
        self.assertEqual(confirm_response.get_json()["status"], "paper_filled")

    def test_position_simulation_api(self) -> None:
        response = self.client.post(
            "/simulation/position",
            json={"symbol": "TEST", "quantity": 5, "entry_price": 110, "forecast_steps": 6, "bars": make_bars()},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["symbol"], "TEST")
        self.assertEqual(len(payload["scenarios"]), 2)
        self.assertGreater(len(payload["forecast_bars"]), 0)


class PortfolioRiskApiTests(unittest.TestCase):
    def setUp(self) -> None:
        from datetime import date, timedelta

        from market_data.store import MarketDataStore

        self.temp_dir = TemporaryDirectory()
        self.market_store = MarketDataStore(Path(self.temp_dir.name) / "market-test.db")
        self.market_store.init_schema()

        start = date(2025, 1, 1)
        for offset, symbol in enumerate(("NVDA", "MSFT", "SPY")):
            bars = []
            price = 100.0 + offset * 20
            for index in range(120):
                price *= 1.001 + (0.002 if index % 3 else -0.001)
                bars.append(
                    {
                        "date": (start + timedelta(days=index)).isoformat(),
                        "open": round(price * 0.998, 4),
                        "high": round(price * 1.01, 4),
                        "low": round(price * 0.99, 4),
                        "close": round(price, 4),
                        "volume": 1_000_000 + index,
                    }
                )
            self.market_store.ingest_daily_bars(symbol, bars, source="test")

        self.trading = TradingStore(Path(self.temp_dir.name) / "trading-test.db")
        self.trading.init_schema()
        self.patch_market = patch("app.market_data_store", self.market_store)
        self.patch_trading = patch("app.trading_store", self.trading)
        self.patch_market.start()
        self.patch_trading.start()
        self.client = app.test_client()

    def tearDown(self) -> None:
        self.patch_market.stop()
        self.patch_trading.stop()
        self.temp_dir.cleanup()

    def test_portfolio_risk_returns_matrix_and_metrics(self) -> None:
        response = self.client.get("/portfolio/risk")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "ok")
        self.assertGreaterEqual(len(payload["symbols"]), 2)
        self.assertIsNotNone(payload["correlation_matrix"])
        self.assertEqual(len(payload["correlation_matrix"]["values"]), len(payload["symbols"]))
        self.assertIn("annualized_vol_pct", payload["portfolio"])
        self.assertIn("hhi", payload["portfolio"])
        self.assertEqual(len(payload["suggested_weights"]), len(payload["symbols"]))

    def test_portfolio_risk_warns_for_missing_history(self) -> None:
        response = self.client.get("/portfolio/risk")

        payload = response.get_json()
        self.assertTrue(any("TSLA" in warning for warning in payload["warnings"]))

    def test_portfolio_risk_empty_portfolio(self) -> None:
        portfolio = self.trading.get_portfolio()
        # Simulate an empty portfolio by selling every position.
        for position in portfolio["positions"]:
            draft = self.trading.create_order(
                {"symbol": position["symbol"], "side": "sell", "quantity": position["quantity"], "order_type": "market"},
                f"sell-{position['symbol']}",
            )
            self.trading.confirm_order(draft["id"])

        response = self.client.get("/portfolio/risk")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "no-positions")


if __name__ == "__main__":
    unittest.main()
