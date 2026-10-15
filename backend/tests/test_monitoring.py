from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import app as app_module  # noqa: E402
from market_data.store import MarketDataStore, normalize_market_symbol  # noqa: E402
from monitoring import MonitorService  # noqa: E402
from trading.store import TradingStore  # noqa: E402


def make_bars(count: int = 40, start_price: float = 100.0) -> list[dict]:
    start = date.today() - timedelta(days=count)
    return [
        {
            "date": (start + timedelta(days=index)).isoformat(),
            "open": start_price + index - 0.3,
            "high": start_price + index + 0.6,
            "low": start_price + index - 0.8,
            "close": start_price + index,
            "volume": 100_000 + index,
        }
        for index in range(count)
    ]


class MonitorStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.market_store = MarketDataStore(root / "market.db")
        self.market_store.init_schema()
        self.trading_store = TradingStore(root / "trading.db")
        self.trading_store.init_schema()
        self.service = MonitorService(self.market_store, self.trading_store)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_market_symbol_normalization(self) -> None:
        self.assertEqual(normalize_market_symbol("nvda", "US"), "NVDA")
        self.assertEqual(normalize_market_symbol("7203", "JP"), "7203.T")
        self.assertEqual(normalize_market_symbol("700", "HK"), "0700.HK")
        self.assertEqual(normalize_market_symbol("0700.HK", "HK"), "0700.HK")
        with self.assertRaises(ValueError):
            normalize_market_symbol("SAP", "EU")

    def test_union_filters_overlap_and_pagination(self) -> None:
        self.market_store.upsert_symbols(
            [
                {"symbol": "NVDA", "name": "NVIDIA", "market": "US", "sector": "Semiconductors", "status": "active"},
                {"symbol": "7203.T", "name": "Toyota", "market": "JP", "exchange": "TSE", "status": "active"},
                {"symbol": "0700.HK", "name": "Tencent", "market": "HK", "exchange": "HKEX", "status": "active"},
            ]
        )
        for symbol in ("NVDA", "7203.T", "0700.HK"):
            self.market_store.ingest_daily_bars(symbol, make_bars(), source="test")
        self.trading_store.set_wanted("NVDA", True)

        all_result = self.service.query({"page_size": 2})
        nvda = self.service.detail("NVDA")
        self.assertEqual(all_result["page_size"], 2)
        self.assertGreater(all_result["pages"], 1)
        self.assertIn("holding", nvda["statuses"])
        self.assertIn("wanted", nvda["statuses"])
        self.assertIn("ai_suggested", nvda["statuses"])

        self.assertEqual([item["symbol"] for item in self.service.query({"market": "JP"})["items"]], ["7203.T"])
        self.assertEqual([item["symbol"] for item in self.service.query({"market": "HK"})["items"]], ["0700.HK"])
        self.assertIn("NVDA", [item["symbol"] for item in self.service.query({"view": "wanted"})["items"]])
        self.assertIn("NVDA", [item["symbol"] for item in self.service.query({"view": "holding"})["items"]])
        self.assertIn("NVDA", [item["symbol"] for item in self.service.query({"view": "ai"})["items"]])
        self.assertEqual(self.service.query({"sector": "Semiconductors"})["total"], 1)
        self.assertGreater(self.service.query({"score_min": 80})["total"], 0)
        self.assertGreater(self.service.query({"freshness": "24h"})["total"], 0)

    def test_preferences_and_settings_persist(self) -> None:
        self.trading_store.set_wanted("AAPL", True)
        saved = self.trading_store.update_monitor_settings({"auto_refresh_enabled": True, "interval_minutes": 7})
        self.assertTrue(saved["auto_refresh_enabled"])
        self.assertEqual(saved["interval_minutes"], 7)

        reopened = TradingStore(self.trading_store.db_path)
        reopened.init_schema()
        self.assertIn("AAPL", reopened.list_wanted_symbols())
        self.assertEqual(reopened.get_monitor_settings()["interval_minutes"], 7)
        with self.assertRaises(ValueError):
            reopened.update_monitor_settings({"interval_minutes": 0})


class MonitorApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.market_store = MarketDataStore(root / "market-api.db")
        self.market_store.init_schema()
        self.trading_store = TradingStore(root / "trading-api.db")
        self.trading_store.init_schema()
        self.market_patch = patch("app.market_data_store", self.market_store)
        self.trading_patch = patch("app.trading_store", self.trading_store)
        self.market_patch.start()
        self.trading_patch.start()
        self.client = app_module.app.test_client()

    def tearDown(self) -> None:
        self.market_patch.stop()
        self.trading_patch.stop()
        self.temp_dir.cleanup()

    def test_add_filter_preference_and_settings_api(self) -> None:
        with patch.object(app_module.stock_ai_pipeline.market_data, "fetch_metadata", return_value={"name": "Tencent", "exchange": "HKEX"}), patch(
            "app._fetch_yahoo_bars", return_value=make_bars()
        ):
            created = self.client.post("/monitor/stocks", json={"symbol": "700", "market": "HK", "sector": "Internet"})
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.get_json()["item"]["symbol"], "0700.HK")

        listed = self.client.get("/monitor/stocks?market=HK&q=Tencent")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.get_json()["total"], 1)

        wanted = self.client.patch("/monitor/stocks/0700.HK/preference", json={"wanted": True})
        self.assertEqual(wanted.status_code, 200)
        self.assertIn("wanted", wanted.get_json()["statuses"])

        settings = self.client.put("/monitor/settings", json={"auto_refresh_enabled": True, "interval_minutes": 30})
        self.assertEqual(settings.status_code, 200)
        self.assertEqual(self.client.get("/monitor/settings").get_json()["interval_minutes"], 30)

    def test_refresh_uses_filtered_symbols_and_keeps_partial_failures(self) -> None:
        self.market_store.upsert_symbols(
            [
                {"symbol": "AAPL", "market": "US", "status": "active"},
                {"symbol": "7203.T", "market": "JP", "status": "active"},
            ]
        )

        def fetch(symbol: str, _range: str) -> list[dict]:
            if symbol == "7203.T":
                raise RuntimeError("temporary upstream failure")
            return make_bars()

        with patch("app._fetch_yahoo_bars", side_effect=fetch):
            response = self.client.post("/monitor/refresh", json={"filters": {"market": "US"}})
        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertIn("AAPL", [item["symbol"] for item in payload["refreshed"]])
        self.assertNotIn("7203.T", [item["symbol"] for item in payload["refreshed"]])
        self.assertEqual(payload["errors"], [])

        with patch("app._fetch_yahoo_bars", side_effect=fetch):
            response = self.client.post("/monitor/refresh", json={"filters": {}})
        payload = response.get_json()
        self.assertIn("AAPL", [item["symbol"] for item in payload["refreshed"]])
        self.assertIn("7203.T", [item["symbol"] for item in payload["errors"]])


if __name__ == "__main__":
    unittest.main()
