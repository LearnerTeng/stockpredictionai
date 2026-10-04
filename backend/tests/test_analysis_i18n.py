from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import app as app_module  # noqa: E402


def analysis_payload(language: str | None = None) -> dict:
    payload = {
        "analysis_mode": "full",
        "prediction": {
            "symbol": "NVDA",
            "history_window": 60,
            "forecast_steps": 3,
            "predictions": [101.0, 102.0, 103.0],
            "actuals": [100.5, 101.5, 102.5],
            "historical_tail": [98.0, 99.0, 100.0],
            "metrics": {"mae": 0.5, "rmse": 0.6},
        },
    }
    if language is not None:
        payload["language"] = language
    return payload


class AnalysisI18nApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = app_module.app.test_client()

    @patch.object(app_module, "_create_openai_client", return_value=None)
    def test_local_analysis_supports_all_ui_languages(self, _client) -> None:
        expected_headings = {"zh-CN": "预测形态", "en": "Forecast Shape", "ja": "予測形状"}
        for language, heading in expected_headings.items():
            with self.subTest(language=language):
                response = self.client.post("/ai/analyze", json=analysis_payload(language))
                self.assertEqual(response.status_code, 200)
                result = response.get_json()
                self.assertEqual(result["language"], language)
                self.assertEqual(result["analysis_mode"], "full")
                self.assertEqual(result["sections"][0]["heading"], heading)

    @patch.object(app_module, "_create_openai_client", return_value=None)
    def test_legacy_request_defaults_to_english(self, _client) -> None:
        response = self.client.post("/ai/analyze", json=analysis_payload())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["language"], "en")

    def test_rejects_unsupported_language(self) -> None:
        response = self.client.post("/ai/analyze", json=analysis_payload("fr"))
        self.assertEqual(response.status_code, 400)
        self.assertIn("language must be one of", response.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
