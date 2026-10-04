from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database.models import Base, Instrument, SentimentAlert, StockPreference  # noqa: E402
from sentiment.classifier import StructuredSentimentClassifier  # noqa: E402
from sentiment.providers import ProviderArticle, canonicalize_url  # noqa: E402
from sentiment.service import NewsIngestionService  # noqa: E402
from sentiment.store import SentimentStore, news_trade_date  # noqa: E402


class FakeProvider:
    name = "fixture"

    def fetch(self, symbol, company_name, start, end, limit=250):
        return [
            ProviderArticle(
                provider=self.name, provider_item_id="one", title="Apple warns on demand",
                url="https://www.reuters.com/markets/apple-demand?utm_source=test", source="Reuters",
                published_at=datetime.now(timezone.utc), summary="Demand is weaker than expected.", language="en",
                symbols=[{"symbol": symbol, "relevance_score": 0.95, "provider_sentiment_score": -0.82}],
            ),
            ProviderArticle(
                provider=self.name, provider_item_id="two", title="Apple cuts guidance",
                url="https://www.bloomberg.com/news/apple-guidance?gclid=123", source="Bloomberg",
                published_at=datetime.now(timezone.utc), summary="Guidance was reduced.", language="en",
                symbols=[{"symbol": symbol, "relevance_score": 0.9, "provider_sentiment_score": -0.7}],
            ),
        ]


class FakeMailer:
    configured = True

    def __init__(self):
        self.messages = []

    def send(self, recipients, subject, text_body, html_body=None):
        self.messages.append((recipients, subject, text_body))
        return {"status": "sent"}


class FlakyMailer(FakeMailer):
    def send(self, recipients, subject, text_body, html_body=None):
        self.messages.append((recipients, subject, text_body))
        if len(self.messages) == 1:
            raise RuntimeError("temporary SMTP failure")
        return {"status": "sent"}


class SentimentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        path = Path(self.temp.name) / "sentiment.db"
        self.store = SentimentStore(f"sqlite:///{path.as_posix()}")
        Base.metadata.create_all(self.store.engine)
        now = datetime.now(timezone.utc)
        with self.store.sessions.begin() as session:
            session.add(Instrument(
                symbol="AAPL", name="Apple", market="US", exchange="NASDAQ", sector="Technology",
                currency="USD", status="active", created_at=now, updated_at=now,
            ))
            session.add(StockPreference(symbol="AAPL", wanted=True, created_at=now, updated_at=now))

    def tearDown(self):
        self.store.engine.dispose()
        self.temp.cleanup()

    def test_url_canonicalization_removes_tracking_parameters(self):
        self.assertEqual(
            canonicalize_url("https://www.reuters.com/a/?utm_source=x&id=2#section"),
            "https://www.reuters.com/a?id=2",
        )

    def test_provider_score_is_normalized_without_openai(self):
        result = StructuredSentimentClassifier(api_key="").classify(
            {"relevance_score": 0.8}, "AAPL", "Apple", -0.6,
        )
        self.assertEqual(result["analysis_status"], "analyzed")
        self.assertEqual(result["sentiment_label"], "negative")
        self.assertAlmostEqual(result["sentiment_score"], -0.6)

    def test_news_is_assigned_after_market_close_without_time_leakage(self):
        self.assertEqual(news_trade_date(datetime(2026, 9, 4, 19, 30, tzinfo=timezone.utc), "US").isoformat(), "2026-09-04")
        self.assertEqual(news_trade_date(datetime(2026, 9, 4, 20, 30, tzinfo=timezone.utc), "US").isoformat(), "2026-09-07")
        self.assertEqual(news_trade_date(datetime(2026, 9, 4, 6, 0, tzinfo=timezone.utc), "JP").isoformat(), "2026-09-04")
        self.assertEqual(news_trade_date(datetime(2026, 9, 4, 7, 0, tzinfo=timezone.utc), "JP").isoformat(), "2026-09-07")

    def test_ingestion_dedupes_aggregates_and_sends_alert(self):
        mailer = FakeMailer()
        service = NewsIngestionService(
            self.store, providers=[FakeProvider()], classifier=StructuredSentimentClassifier(api_key=""),
            mailer=mailer, sleeper=lambda _: None,
        )
        self.store.update_settings({
            "email_enabled": True, "email_recipients": ["owner@example.com"],
            "primary_domains": ["reuters.com", "bloomberg.com"], "notification_language": "ja",
        }, smtp_configured=True)
        job = service.enqueue(symbols=["AAPL"])
        result = service.run(job["id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["records_received"], 2)
        snapshot = self.store.snapshot("AAPL")
        self.assertTrue(snapshot["negative_shock"])
        self.assertLess(snapshot["score_1d"], -0.6)
        self.assertEqual(snapshot["source_count"], 2)
        self.assertEqual(len(mailer.messages), 1)
        self.assertIn("ネガティブセンチメント急変", mailer.messages[0][1])

        overview = self.store.overview({"market": "US", "window": "24h"})
        self.assertEqual(overview["summary"]["articles"], 2)
        self.assertEqual(overview["articles"][0]["source_tier"], "primary")
        with self.store.sessions() as session:
            self.assertEqual(session.query(SentimentAlert).count(), 1)

    def test_missing_openai_keeps_unscored_article_pending(self):
        article = ProviderArticle(
            provider="fixture", provider_item_id="jp", title="業績予想を発表",
            url="https://example.jp/news/1", source="Example", published_at=datetime.now(timezone.utc),
            language="Japanese", symbols=[{"symbol": "AAPL", "relevance_score": 0.6}],
        ).normalized()
        _, ids = self.store.upsert_article(article)
        item = self.store.pending_relations(ids=ids)[0]
        result = StructuredSentimentClassifier(api_key="").classify(item, "AAPL", "Apple", None)
        self.store.save_analysis(item["id"], result)
        self.assertEqual(self.store.pending_relations(ids=ids)[0]["id"], item["id"])

    def test_failed_alert_is_retried_and_recent_event_is_deduped(self):
        mailer = FlakyMailer()
        service = NewsIngestionService(
            self.store, providers=[FakeProvider()], classifier=StructuredSentimentClassifier(api_key=""),
            mailer=mailer, sleeper=lambda _: None,
        )
        self.store.update_settings({
            "email_enabled": True, "email_recipients": ["owner@example.com"],
            "primary_domains": ["reuters.com", "bloomberg.com"], "notification_language": "en",
        }, smtp_configured=True)
        result = service.run(service.enqueue(symbols=["AAPL"])["id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(service.retry_failed_alerts(), 1)
        snapshot = self.store.snapshot("AAPL")
        service._send_shock_alert("AAPL", snapshot, self.store.settings(smtp_configured=True))
        with self.store.sessions() as session:
            alerts = session.query(SentimentAlert).all()
            self.assertEqual(len(alerts), 1)
            self.assertEqual(alerts[0].status, "sent")
            self.assertEqual(alerts[0].payload["email_attempts"], 2)


if __name__ == "__main__":
    unittest.main()
