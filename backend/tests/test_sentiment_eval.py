from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flask import Flask
from sqlalchemy import create_engine
from database.models import Base, BarRevision, Instrument, NewsItem, NewsModelRun, ResearchDocument, Security
from database.session import session_factory
from market_data.calendar import calendar, session_close
from sentiment.line_api import register_line_api
from sentiment.model_lines import VERSION
from stock_ai.sentiment_eval import evaluate_sentiment


class SentimentEvaluationTests(TestCase):
    def test_paired_us_jp_folds_ignore_delayed_news_and_quote_history(self):
        with TemporaryDirectory() as tmp:
            engine = create_engine(f"sqlite:///{Path(tmp) / 'research.db'}")
            try:
                Base.metadata.create_all(engine)
                sessions = session_factory(engine)
                self.exercise(sessions)
            finally:
                engine.dispose()

    def exercise(self, sessions):
        pin = dict(model="fixture", version=VERSION, provider="fixture")
        first, last = "2025-01-06", "2025-11-28"
        as_of = datetime(2025, 11, 30, tzinfo=timezone.utc)
        with sessions.begin() as session:
            for market, symbol, benchmark in (("US", "FIXUS", "SPY"), ("JP", "FIXJP.T", "1306.T")):
                currency = "JPY" if market == "JP" else "USD"
                for key in (symbol, benchmark):
                    session.add(Instrument(symbol=key, name=key, market=market, currency=currency,
                                           status="active", created_at=as_of, updated_at=as_of))
                    session.add(Security(id=key, market=market, currency=currency, provisional=True))
                session.flush()
                for index, label in enumerate(calendar(market).sessions_in_range(first, last)):
                    day = label.date()
                    close = session_close(day, market)
                    for key, offset in ((symbol, index % 13), (benchmark, 0)):
                        price = 100 + index / 20 + offset / 5
                        session.add(BarRevision(id=f"{key}-{index}", security_id=key, symbol=key, trade_date=day,
                            source="fixture", revision=1, available_at=close + timedelta(minutes=5),
                            ingested_at=close + timedelta(minutes=7), quality_status="accepted", checksum="fixture",
                            payload=dict(close=price, adj_close=price, volume=20000 + index)))
                    if index % 2:
                        continue
                    for tag, minutes in (("on-time", 20), ("late", 31)):
                        key = f"{market}-{index}-{tag}"
                        published = close - timedelta(minutes=5)
                        session.add(NewsItem(id=key, title=key, source="fixture", published_at=published, fetched_at=close))
                        session.flush()
                        session.add(ResearchDocument(id=key, article_id=key, revision=1, checksum=key,
                            title=key, body=key, source="fixture", symbols=[symbol], published_at=published,
                            available_at=close))
                        session.flush()
                        session.add(NewsModelRun(id=key, document_id=key, line="deepseek", model=pin["model"],
                            status="ready", attempts=1, retry_at=close, completed_at=close + timedelta(minutes=minutes),
                            payload=pin, result=dict(output=dict(scores=[dict(symbol=symbol, score=.4)],
                                facts=[dict(symbol=symbol)]))))
        inputs = dict(start=first, end=last, as_of=as_of.isoformat(), symbols=["FIXUS", "FIXJP.T"],
                      line="deepseek", model_pins={"deepseek": pin})
        app = Flask(__name__)
        from types import SimpleNamespace
        register_line_api(app, lambda: (SimpleNamespace(sessions=sessions), None), None)
        client = app.test_client()
        response = client.post("/sentiment/lines/evaluation", json=inputs)
        self.assertEqual(response.status_code, 200, response.json)
        report = response.json
        self.assertEqual(report["benchmarks"], {"US": "SPY", "JP": "1306.T"})
        self.assertEqual(report, client.get("/sentiment/lines/evaluation").json["report"])
        self.assertEqual(report, evaluate_sentiment(sessions, report["inputs"], clock=as_of))
        for market, rows in report["metrics"].items():
            self.assertTrue(all(row["status"] == "ready" and row["samples"] >= 3 for row in rows))
            for item in report["observations"][market]["5"]:
                cutoff = datetime.fromisoformat(item["cutoff"])
                origin = next(i for i, day in enumerate(calendar(market).sessions_in_range(first, last))
                              if day.date().isoformat() == item["date"])
                self.assertNotIn(f"{market}-{origin}-late", item["news_run_ids"])
                self.assertEqual(cutoff, session_close(datetime.fromisoformat(item["date"]).date(), market) + timedelta(minutes=30))
        inputs["model_pins"]["deepseek"] = {**pin, "model": "no-recorded-runs"}
        insufficient = evaluate_sentiment(sessions, inputs, clock=as_of)
        self.assertTrue(all(row["status"] == "insufficient_data" for rows in insufficient["metrics"].values() for row in rows))
